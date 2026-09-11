"""Tests de las herramientas del chat.

Es la parte pura del asistente: dado un `DataAccess` en memoria, cada
herramienta compone una respuesta de texto. Se testea sin Ollama, que es la
unica pieza no reproducible del proyecto.

El foco esta en los tres fallos que aparecieron al probar el chat de verdad
contra el modelo pequeño:

1. Una temporada que el modelo se inventa (con forma de codigo valido, como
   "2022") debia caer al valor por defecto en lugar de dar una respuesta vacia
   con aire de certeza.
2. La direccion de la PPDA la interpreta la herramienta, no el modelo: un PPDA
   bajo es presion alta, y un modelo de 3B lo lee al reves si se le deja.
3. Cada respuesta nombra la temporada de forma explicita, para que el modelo no
   tenga que redactarla por su cuenta y se la invente.
"""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.api import cache, services
from futbol_analytics.chat import tools
from tests.conftest import FakeDataAccess

TEMPORADA = "2526"


@pytest.fixture(autouse=True)
def cache_limpia() -> None:
    """Cada test parte de cache vacia: las claves incluyen la version de los
    datos, y `FakeDataAccess` siempre usa "v1" por defecto, asi que sin esto un
    test heredaria el resultado calculado por otro con datos distintos."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def data(jugadores: pd.DataFrame, equipos: pd.DataFrame) -> FakeDataAccess:
    return FakeDataAccess(jugadores, equipos)


# --- Catalogo de herramientas ------------------------------------------------


def test_definitions_declara_las_cuatro_herramientas() -> None:
    nombres = {d["function"]["name"] for d in tools.definitions()}
    assert nombres == {
        "perfil_de_jugador",
        "comparar_jugadores",
        "buscar_jugadores",
        "estilo_de_equipo",
    }


def test_dispatch_con_herramienta_desconocida_no_revienta(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch("inventada", {}, data, TEMPORADA)

    assert "inventada" in respuesta
    assert "No existe" in respuesta


def test_dispatch_si_la_herramienta_falla_lo_cuenta_y_no_propaga(
    data: FakeDataAccess, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _rompe(*_args: object, **_kwargs: object) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(tools, "_perfil", _rompe)

    respuesta = tools.dispatch("perfil_de_jugador", {"jugador": "Pedri"}, data, TEMPORADA)

    assert "No se ha podido responder" in respuesta
    assert "boom" in respuesta


# --- La temporada se valida contra las cargadas, no contra su formato -------


def test_temporada_con_forma_valida_pero_no_cargada_cae_al_valor_por_defecto(
    data: FakeDataAccess,
) -> None:
    # "2022" tiene forma de codigo de temporada (cuatro digitos) pero no esta
    # entre las cargadas: es exactamente lo que el modelo se inventaba cuando
    # la pregunta no mencionaba temporada.
    respuesta = tools.dispatch(
        "buscar_jugadores", {"metrica": "np_xg", "temporada": "2022"}, data, TEMPORADA
    )

    assert f"En la temporada {TEMPORADA}" in respuesta
    assert "2022" not in respuesta


def test_temporada_con_palabra_suelta_cae_al_valor_por_defecto(data: FakeDataAccess) -> None:
    # El modelo arrastra palabras de la pregunta: ante "esta temporada" llego a
    # mandar literalmente `temporada="esta"`.
    respuesta = tools.dispatch(
        "buscar_jugadores", {"metrica": "np_xg", "temporada": "esta"}, data, TEMPORADA
    )

    assert f"En la temporada {TEMPORADA}" in respuesta


def test_temporada_cargada_se_respeta(data: FakeDataAccess) -> None:
    assert TEMPORADA in data.seasons()

    respuesta = tools.dispatch(
        "buscar_jugadores", {"metrica": "np_xg", "temporada": TEMPORADA}, data, "otra"
    )

    assert f"En la temporada {TEMPORADA}" in respuesta


# --- perfil_de_jugador --------------------------------------------------------


def test_perfil_nombra_la_temporada_y_destaca_al_mejor_del_grupo(data: FakeDataAccess) -> None:
    percentiles = services.player_percentiles(data, TEMPORADA)
    fuerte = percentiles[
        (percentiles["percentile_per90"] >= tools.DESTACABLE)
        & (percentiles["higher_is_better"] == True)  # noqa: E712
    ]
    assert not fuerte.empty, "el fixture debe producir al menos un destacado"
    jugador = fuerte.iloc[0]["player"]

    respuesta = tools.dispatch("perfil_de_jugador", {"jugador": jugador}, data, TEMPORADA)

    assert f"En la temporada {TEMPORADA}:" in respuesta
    assert jugador in respuesta
    assert "Destaca en:" in respuesta


def test_perfil_de_jugador_inexistente_no_inventa_a_nadie(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch(
        "perfil_de_jugador", {"jugador": "Futbolista Que No Existe"}, data, TEMPORADA
    )

    assert "No encuentro" in respuesta
    assert TEMPORADA in respuesta


def test_perfil_de_suplente_bajo_el_umbral_de_minutos_no_aparece(data: FakeDataAccess) -> None:
    # "Suplente" existe en los datos crudos pero con 90 minutos, por debajo del
    # umbral que exige la poblacion de percentiles: no debe confundirse con un
    # jugador que sencillamente no esta en las Big 5.
    respuesta = tools.dispatch("perfil_de_jugador", {"jugador": "Suplente"}, data, TEMPORADA)

    assert "No encuentro" in respuesta


# --- comparar_jugadores -------------------------------------------------------


def test_comparar_posiciones_distintas_avisa_en_lugar_de_comparar(data: FakeDataAccess) -> None:
    percentiles = services.player_percentiles(data, TEMPORADA)
    un_df = percentiles[percentiles["position_group"] == "DF"].iloc[0]["player"]
    un_fw = percentiles[percentiles["position_group"] == "FW"].iloc[0]["player"]

    respuesta = tools.dispatch(
        "comparar_jugadores", {"jugador_a": un_df, "jugador_b": un_fw}, data, TEMPORADA
    )

    assert "poblaciones distintas" in respuesta


def test_comparar_misma_posicion_nombra_la_temporada_y_las_diferencias(
    data: FakeDataAccess,
) -> None:
    percentiles = services.player_percentiles(data, TEMPORADA)
    mf = percentiles[percentiles["position_group"] == "MF"]["player"].unique()
    assert len(mf) >= 2

    respuesta = tools.dispatch(
        "comparar_jugadores", {"jugador_a": mf[0], "jugador_b": mf[1]}, data, TEMPORADA
    )

    assert f"En la temporada {TEMPORADA}, comparando {mf[0]} y {mf[1]}" in respuesta


def test_comparar_con_jugador_inexistente_lo_dice(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch(
        "comparar_jugadores",
        {"jugador_a": "Nadie De Nadie", "jugador_b": "Tampoco Este"},
        data,
        TEMPORADA,
    )

    assert "No encuentro" in respuesta


# --- buscar_jugadores ----------------------------------------------------------


def test_buscar_metrica_desconocida_lista_las_disponibles(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch("buscar_jugadores", {"metrica": "esto_no_existe"}, data, TEMPORADA)

    assert "No conozco la métrica" in respuesta


def test_buscar_por_posicion_sin_resultados_lo_dice(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch(
        "buscar_jugadores", {"metrica": "np_xg", "posicion": "GK"}, data, TEMPORADA
    )

    assert "Ningún jugador de esa posición" in respuesta


def test_buscar_devuelve_los_mejores_con_la_temporada_explicita(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch(
        "buscar_jugadores", {"metrica": "np_xg", "posicion": "FW"}, data, TEMPORADA
    )

    assert f"En la temporada {TEMPORADA}, los mejores en" in respuesta


# --- estilo_de_equipo ----------------------------------------------------------


def test_estilo_con_ppda_bajo_dice_que_presiona_arriba(data: FakeDataAccess) -> None:
    # "Equipo 0" tiene el PPDA mas bajo del fixture (6.0): presiona muy arriba,
    # no "poco", que es justo lo que el modelo llego a decir al interpretar el
    # numero por su cuenta.
    respuesta = tools.dispatch("estilo_de_equipo", {"equipo": "Equipo 0"}, data, TEMPORADA)

    assert "Presiona muy arriba" in respuesta
    assert f"En la temporada {TEMPORADA}" in respuesta


def test_estilo_con_ppda_alto_dice_que_presiona_poco(data: FakeDataAccess) -> None:
    # "Equipo 9" tiene el PPDA mas alto del fixture (16.8): espera atras.
    respuesta = tools.dispatch("estilo_de_equipo", {"equipo": "Equipo 9"}, data, TEMPORADA)

    assert "Presiona poco y espera atras" in respuesta


def test_estilo_de_equipo_inexistente_lo_dice(data: FakeDataAccess) -> None:
    respuesta = tools.dispatch("estilo_de_equipo", {"equipo": "Un Equipo Raro"}, data, TEMPORADA)

    assert "No tengo cargado" in respuesta
