"""Tests del esquema y de la construccion del UPSERT.

No levantan PostgreSQL: comprueban la definicion de las tablas y compilan la
sentencia contra el dialecto de PostgreSQL, que es suficiente para detectar los
errores que importan.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from futbol_analytics.db.schema import etl_run, player_season, team_season
from futbol_analytics.etl.load import build_upsert
from futbol_analytics.metrics import PLAYER_METRICS, TEAM_METRICS

IDENTIDAD_JUGADOR = {
    "league",
    "season",
    "team",
    "player",
    "nation",
    "age",
    "born",
    "position_raw",
    "position_group",
    "detailed_position",
    "updated_at",
}


def test_cada_metrica_del_catalogo_tiene_columna() -> None:
    columnas = set(player_season.c.keys())

    for metric in PLAYER_METRICS:
        assert metric.name in columnas, f"falta la columna {metric.name}"


def test_ninguna_metrica_choca_con_una_columna_de_identidad() -> None:
    # Si alguien anadiese al catalogo una metrica llamada "age" o "team", la
    # tabla se construiria con dos columnas del mismo nombre.
    nombres = {metric.name for metric in PLAYER_METRICS}

    assert not (nombres & IDENTIDAD_JUGADOR)


def test_la_clave_de_jugador_admite_cambios_de_equipo_a_mitad_de_temporada() -> None:
    # El equipo forma parte de la clave: un jugador traspasado en enero tiene
    # una fila por etapa, y eso es lo correcto analiticamente.
    assert set(player_season.primary_key.columns.keys()) == {"league", "season", "team", "player"}


def test_las_metricas_son_nullable() -> None:
    # Un hueco de FBref debe quedar como NULL. Un cero seria una afirmacion.
    for metric in PLAYER_METRICS:
        assert player_season.c[metric.name].nullable, metric.name


def test_la_posicion_detallada_existe_pero_se_deja_vacia_en_esta_fase() -> None:
    # La rellenara el clustering de roles: FBref no publica posicion detallada
    # a nivel de temporada.
    columna = player_season.c["detailed_position"]

    assert columna.nullable
    assert "fase 3" in (columna.comment or "")


def test_team_season_guarda_las_dos_perspectivas() -> None:
    # Sin la fila "against" no se puede derivar nada que dependa del rival,
    # como una PPDA aproximada.
    assert set(team_season.primary_key.columns.keys()) == {
        "league",
        "season",
        "team",
        "perspective",
    }
    for metric in TEAM_METRICS:
        assert metric.name in team_season.c


def test_etl_run_registra_el_resultado_de_cada_carga() -> None:
    assert {"status", "started_at", "finished_at", "error"} <= set(etl_run.c.keys())


# --- UPSERT -----------------------------------------------------------------


def _sql(rows: list[dict]) -> str:
    return str(build_upsert(player_season, rows).compile(dialect=postgresql.dialect())).lower()


def test_el_upsert_actualiza_en_lugar_de_duplicar() -> None:
    # El ETL se relanza cada semana sobre la temporada en curso y FBref corrige
    # datos a posteriori: relanzar tiene que actualizar, no duplicar.
    sql = _sql(
        [
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": "Barcelona",
                "player": "Pedri",
                "goals": 3,
            }
        ]
    )

    assert "on conflict" in sql
    assert "do update" in sql
    assert "excluded.goals" in sql


def test_el_upsert_no_reescribe_las_columnas_clave() -> None:
    sql = _sql(
        [
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": "Barcelona",
                "player": "Pedri",
                "goals": 3,
            }
        ]
    )

    conflicto, _, actualizacion = sql.partition("do update set")
    assert "excluded.player" not in actualizacion
    assert "excluded.league" not in actualizacion
    assert conflicto  # la clave si aparece en la clausula ON CONFLICT


def test_el_upsert_solo_toca_las_columnas_que_vienen_en_los_datos() -> None:
    # Una carga parcial no debe borrar `detailed_position`, que escribe otro
    # proceso (el clustering de la fase 3).
    sql = _sql(
        [
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": "Barcelona",
                "player": "Pedri",
                "goals": 3,
            }
        ]
    )

    assert "excluded.detailed_position" not in sql
    assert "excluded.interceptions" not in sql


def test_el_upsert_refresca_la_marca_de_tiempo() -> None:
    sql = _sql(
        [
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": "Barcelona",
                "player": "Pedri",
                "goals": 3,
            }
        ]
    )

    assert "updated_at = now()" in sql
