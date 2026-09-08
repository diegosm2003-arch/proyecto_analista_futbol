"""Tests de la API.

No levantan PostgreSQL: el acceso a datos se sustituye por DataFrames en memoria
mediante `app.dependency_overrides`. Eso permite comprobar el contrato completo,
incluido el encadenado datos -> roles -> percentiles.
"""

from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from futbol_analytics import __version__
from futbol_analytics.analysis.roles import ARCHETYPES
from futbol_analytics.api import cache
from futbol_analytics.templates import PIZZA_TEMPLATES

TEMPORADA = "2526"


# --- Infraestructura --------------------------------------------------------


def test_health_informa_de_la_version_de_los_datos(client: TestClient) -> None:
    respuesta = client.get("/health")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "ok"
    assert cuerpo["version"] == __version__
    # Es lo que permite saber si se esta viendo el ultimo scraping.
    assert cuerpo["data_version"] == "v1"


# --- Catalogo ---------------------------------------------------------------


def test_el_catalogo_expone_temporadas_ligas_y_umbral(client: TestClient) -> None:
    cuerpo = client.get("/meta/catalog").json()

    assert cuerpo["seasons"] == [TEMPORADA]
    assert "ESP-La Liga" in cuerpo["leagues"]
    assert cuerpo["min_minutes"] > 0


def test_el_catalogo_de_metricas_omite_las_que_no_se_normalizan(client: TestClient) -> None:
    nombres = {metrica["name"] for metrica in client.get("/meta/metrics").json()}

    assert "goals" in nombres
    # Los minutos son el denominador, no una metrica que comparar.
    assert "minutes" not in nombres


def test_las_metricas_de_estilo_se_marcan_como_sin_direccion(client: TestClient) -> None:
    # Para que la interfaz no las pinte como buenas ni como malas.
    metricas = {m["name"]: m for m in client.get("/meta/metrics").json()}

    assert metricas["clearances"]["higher_is_better"] is None
    assert metricas["goals"]["higher_is_better"] is True
    assert metricas["fouls_committed"]["higher_is_better"] is False


def test_las_metricas_defensivas_se_marcan_como_ajustables(client: TestClient) -> None:
    metricas = {m["name"]: m for m in client.get("/meta/metrics").json()}

    assert metricas["tackles"]["possession_sensitive"] is True
    assert metricas["goals"]["possession_sensitive"] is False


def test_los_roles_publicados_son_los_del_catalogo(client: TestClient) -> None:
    roles = client.get("/meta/roles").json()

    esperados = sum(len(arquetipos) for arquetipos in ARCHETYPES.values())
    assert len(roles) == esperados
    assert all(rol["description"] for rol in roles)


def test_las_plantillas_del_grafico_se_sirven_desde_la_api(client: TestClient) -> None:
    # La interfaz y el chat tienen que pintar los mismos ejes: si cada cliente
    # eligiera los suyos, dos graficos del mismo jugador no serian comparables.
    plantillas = {p["position_group"]: p for p in client.get("/meta/templates").json()}

    assert set(plantillas) == set(PIZZA_TEMPLATES)
    for plantilla in plantillas.values():
        assert 8 <= len(plantilla["slices"]) <= 12
        assert all(porcion["label"] for porcion in plantilla["slices"])


def test_los_porteros_no_tienen_plantilla_publicada(client: TestClient) -> None:
    plantillas = {p["position_group"] for p in client.get("/meta/templates").json()}

    assert "GK" not in plantillas


# --- Busqueda de jugadores --------------------------------------------------


def test_la_busqueda_devuelve_jugadores_con_su_rol(client: TestClient) -> None:
    jugadores = client.get("/players", params={"season": TEMPORADA, "limit": 500}).json()

    assert len(jugadores) == 123
    con_rol = [j for j in jugadores if j["detailed_position"]]
    assert con_rol, "el clustering deberia haber asignado roles"


def test_la_busqueda_filtra_por_liga(client: TestClient) -> None:
    jugadores = client.get(
        "/players", params={"season": TEMPORADA, "league": "ESP-La Liga", "limit": 500}
    ).json()

    assert {j["league"] for j in jugadores} == {"ESP-La Liga"}


def test_la_busqueda_filtra_por_posicion(client: TestClient) -> None:
    jugadores = client.get(
        "/players", params={"season": TEMPORADA, "position_group": "DF", "limit": 500}
    ).json()

    assert {j["position_group"] for j in jugadores} == {"DF"}
    assert len(jugadores) == 40


def test_la_busqueda_por_nombre_es_parcial(client: TestClient) -> None:
    jugadores = client.get("/players", params={"season": TEMPORADA, "name": "traspas"}).json()

    assert {j["player"] for j in jugadores} == {"Traspasado"}
    # Dos etapas, dos filas: no se promedian.
    assert len(jugadores) == 2


def test_la_busqueda_pagina(client: TestClient) -> None:
    primera = client.get("/players", params={"season": TEMPORADA, "limit": 5}).json()
    segunda = client.get("/players", params={"season": TEMPORADA, "limit": 5, "offset": 5}).json()

    assert len(primera) == 5
    assert {j["player"] for j in primera}.isdisjoint({j["player"] for j in segunda})


def test_una_temporada_sin_datos_da_404(client: TestClient) -> None:
    respuesta = client.get("/players", params={"season": "1999"})

    assert respuesta.status_code == 404
    assert "1999" in respuesta.json()["detail"]


# --- Perfil de percentiles --------------------------------------------------


def test_el_perfil_devuelve_percentiles_ordenados(client: TestClient) -> None:
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    percentiles = [m["percentile"] for m in cuerpo["metrics"] if m["percentile"] is not None]
    assert percentiles == sorted(percentiles, reverse=True)
    assert all(0.0 <= p <= 100.0 for p in percentiles)


def test_el_perfil_informa_del_tamano_de_la_poblacion(client: TestClient) -> None:
    # Un percentil contra 40 jugadores y otro contra 400 no valen lo mismo.
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    assert cuerpo["population_group"] == "DF"
    assert cuerpo["population_size"] == 40


def test_el_perfil_de_un_defensa_no_incluye_metricas_de_portero(client: TestClient) -> None:
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    nombres = {m["metric"] for m in cuerpo["metrics"]}
    assert "saves" not in nombres
    assert "goals_against" not in nombres
    assert "clearances" in nombres


def test_el_perfil_avisa_de_que_df_mezcla_centrales_y_laterales(client: TestClient) -> None:
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    assert any("centrales y laterales" in aviso for aviso in cuerpo["caveats"])


def test_el_perfil_avisa_cuando_la_poblacion_es_pequena(client: TestClient) -> None:
    # 40 defensas estan por debajo del umbral de fiabilidad.
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    assert any("fragil" in aviso for aviso in cuerpo["caveats"])


def test_un_jugador_inexistente_da_404(client: TestClient) -> None:
    respuesta = client.get("/players/Nadie/profile", params={"season": TEMPORADA})

    assert respuesta.status_code == 404


def test_un_jugador_por_debajo_del_umbral_no_tiene_perfil(client: TestClient) -> None:
    # Existe en la busqueda, pero no es comparable: 90 minutos no dan percentil.
    respuesta = client.get("/players/Suplente/profile", params={"season": TEMPORADA})

    assert respuesta.status_code == 404


def test_un_traspaso_obliga_a_indicar_el_equipo(client: TestClient) -> None:
    # Promediar sus dos etapas ocultaria el cambio de contexto, que suele ser lo
    # interesante. La API prefiere preguntar antes que inventarse una media.
    respuesta = client.get("/players/Traspasado/profile", params={"season": TEMPORADA})

    assert respuesta.status_code == 409
    assert "Equipo 1" in respuesta.json()["detail"]


def test_indicando_el_equipo_el_traspaso_se_resuelve(client: TestClient) -> None:
    respuesta = client.get(
        "/players/Traspasado/profile", params={"season": TEMPORADA, "team": "Equipo 7"}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["player"]["team"] == "Equipo 7"


def test_la_poblacion_por_rol_es_mas_estrecha_que_por_posicion(client: TestClient) -> None:
    por_posicion = client.get(
        "/players/DF 0/profile", params={"season": TEMPORADA, "population": "position"}
    ).json()
    por_rol = client.get(
        "/players/DF 0/profile", params={"season": TEMPORADA, "population": "role"}
    ).json()

    assert por_posicion["population_group"] == "DF"
    assert por_rol["population_group"] in {a.name for a in ARCHETYPES["DF"]}
    assert por_rol["population_size"] < por_posicion["population_size"]


def test_una_base_de_comparacion_invalida_da_422(client: TestClient) -> None:
    respuesta = client.get(
        "/players/DF 0/profile", params={"season": TEMPORADA, "basis": "inventada"}
    )

    assert respuesta.status_code == 422


def test_el_ajuste_por_posesion_esta_disponible_con_datos_de_equipo(client: TestClient) -> None:
    cuerpo = client.get(
        "/players/DF 0/profile", params={"season": TEMPORADA, "basis": "padj"}
    ).json()

    entradas = next(m for m in cuerpo["metrics"] if m["metric"] == "tackles")
    assert entradas["padj"] is not None
    assert entradas["percentile"] is not None


# --- Estilo de equipo -------------------------------------------------------


def test_los_estilos_cubren_a_todos_los_equipos(client: TestClient) -> None:
    cuerpo = client.get("/teams/styles", params={"season": TEMPORADA}).json()

    assert len(cuerpo["teams"]) == 10
    assert all(equipo["style"] for equipo in cuerpo["teams"])
    assert cuerpo["n_styles"] == 5


def test_el_informe_de_estilos_incluye_la_calidad_de_la_particion(client: TestClient) -> None:
    cuerpo = client.get("/teams/styles", params={"season": TEMPORADA}).json()

    assert cuerpo["silhouette"] is not None


def test_los_estilos_se_filtran_por_liga_despues_de_agrupar(client: TestClient) -> None:
    # El clustering usa todas las ligas cargadas: un estilo de LaLiga solo
    # significa algo comparado con el resto de Europa.
    cuerpo = client.get(
        "/teams/styles", params={"season": TEMPORADA, "league": "ENG-Premier League"}
    ).json()

    assert cuerpo["teams"] == []
    assert cuerpo["silhouette"] is not None


def test_un_numero_de_estilos_fuera_de_rango_da_422(client: TestClient) -> None:
    respuesta = client.get("/teams/styles", params={"season": TEMPORADA, "n_styles": 99})

    assert respuesta.status_code == 422


# --- Cache ------------------------------------------------------------------


def test_el_calculo_no_se_repite_entre_peticiones(client: TestClient) -> None:
    client.get("/players", params={"season": TEMPORADA})
    tras_la_primera = cache.size()
    client.get("/players", params={"season": TEMPORADA})

    assert cache.size() == tras_la_primera


def test_una_carga_nueva_del_etl_invalida_lo_cacheado(
    client: TestClient,
    jugadores: pd.DataFrame,
    equipos: pd.DataFrame,
) -> None:
    from futbol_analytics.api import services
    from tests.conftest import FakeDataAccess

    antigua = FakeDataAccess(jugadores, equipos, version="v1")
    nueva = FakeDataAccess(jugadores, equipos, version="v2")

    services.enriched_players(antigua, TEMPORADA)
    entradas = cache.size()
    services.enriched_players(nueva, TEMPORADA)

    # La version de los datos forma parte de la clave: no se reutiliza.
    assert cache.size() == entradas + 1


# --- Contexto de la poblacion -----------------------------------------------


def test_el_perfil_dice_cuantas_ligas_sostienen_el_percentil(client: TestClient) -> None:
    cuerpo = client.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()

    assert cuerpo["population_leagues"] == 5
    assert cuerpo["min_minutes_applied"] == 450


def test_con_una_sola_liga_cargada_el_perfil_avisa(
    equipos: pd.DataFrame,
    jugadores: pd.DataFrame,
) -> None:
    # Cargar solo LaLiga es legitimo para probar, pero rompe la premisa del
    # producto: el percentil se calcula contra las Big 5.
    from futbol_analytics.api import cache
    from futbol_analytics.api.dependencies import get_data_access
    from futbol_analytics.api.main import app
    from tests.conftest import FakeDataAccess

    solo_laliga = jugadores[jugadores["league"] == "ESP-La Liga"]
    cache.clear()
    app.dependency_overrides[get_data_access] = lambda: FakeDataAccess(solo_laliga, equipos)
    try:
        with TestClient(app) as cliente:
            cuerpo = cliente.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()
    finally:
        app.dependency_overrides.clear()
        cache.clear()

    assert cuerpo["population_leagues"] == 1
    assert any("grandes ligas" in aviso for aviso in cuerpo["caveats"])


def test_con_la_temporada_empezada_el_perfil_avisa(
    equipos: pd.DataFrame,
    jugadores: pd.DataFrame,
) -> None:
    # En la jornada 4 el umbral baja para que la plataforma no salga vacia, pero
    # eso no hace fiables los ratios por 90 y hay que decirlo.
    from futbol_analytics.api import cache
    from futbol_analytics.api.dependencies import get_data_access
    from futbol_analytics.api.main import app
    from tests.conftest import FakeDataAccess

    empezada = jugadores.copy()
    empezada["minutes"] = 360
    cache.clear()
    app.dependency_overrides[get_data_access] = lambda: FakeDataAccess(empezada, equipos)
    try:
        with TestClient(app) as cliente:
            cuerpo = cliente.get("/players/DF 0/profile", params={"season": TEMPORADA}).json()
    finally:
        app.dependency_overrides.clear()
        cache.clear()

    assert cuerpo["min_minutes_applied"] == 108
    assert any("Temporada empezada" in aviso for aviso in cuerpo["caveats"])


# --- Estado del ETL ---------------------------------------------------------


def test_health_informa_del_ultimo_intento_de_carga(client: TestClient) -> None:
    # `data_version` sola enmascara un problema: si la carga programada falla,
    # la fecha de la ultima carga correcta sigue ahi tan tranquila.
    cuerpo = client.get("/health").json()

    assert cuerpo["last_etl_status"] == "success"


def test_el_historial_de_cargas_se_publica(client: TestClient) -> None:
    ejecuciones = client.get("/meta/etl").json()

    assert len(ejecuciones) == 1
    assert ejecuciones[0]["status"] == "success"
    assert ejecuciones[0]["player_rows"] == 123


def test_una_carga_fallida_se_ve_en_health(
    equipos: pd.DataFrame,
    jugadores: pd.DataFrame,
) -> None:
    # Nadie mira los logs de un contenedor: si el ETL programado revienta un
    # martes de madrugada, tiene que verse en la interfaz.
    from datetime import UTC, datetime

    from futbol_analytics.api import cache
    from futbol_analytics.api.dependencies import get_data_access
    from futbol_analytics.api.main import app
    from tests.conftest import FakeDataAccess

    fallida = [
        {
            "id": 2,
            "status": "failed",
            "started_at": datetime(2026, 9, 8, 6, 0, tzinfo=UTC),
            "finished_at": datetime(2026, 9, 8, 6, 2, tzinfo=UTC),
            "leagues": "ESP-La Liga",
            "seasons": "2627",
            "player_rows": None,
            "team_rows": None,
            "error": "FBref no responde",
        }
    ]
    cache.clear()
    app.dependency_overrides[get_data_access] = lambda: FakeDataAccess(
        jugadores, equipos, runs=fallida
    )
    try:
        with TestClient(app) as cliente:
            salud = cliente.get("/health").json()
            historial = cliente.get("/meta/etl").json()
    finally:
        app.dependency_overrides.clear()
        cache.clear()

    assert salud["last_etl_status"] == "failed"
    # La fecha de la ultima carga CORRECTA sigue existiendo: por eso hace falta
    # el estado aparte.
    assert salud["data_version"] == "v1"
    assert historial[0]["error"] == "FBref no responde"
