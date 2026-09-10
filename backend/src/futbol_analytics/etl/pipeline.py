"""Orquestacion del ETL: extraer, transformar, cargar.

Cada paso vive en su modulo; aqui solo se encadenan y se registra el resultado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from futbol_analytics.config import BIG_5_LEAGUES, get_settings
from futbol_analytics.db import create_schema, get_engine, player_season, team_season
from futbol_analytics.db.schema import player_match, shot_event
from futbol_analytics.etl import extract, load, transform, understat_source
from futbol_analytics.metrics import PLAYER_METRICS, TEAM_METRICS, stat_types

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Resumen de una ejecucion."""

    player_rows: int
    team_rows: int
    shot_rows: int = 0
    match_rows: int = 0


def run(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    load_players: bool = True,
    load_teams: bool = True,
    dry_run: bool = False,
    use_cache: bool | None = None,
    load_shots: bool = True,
    load_matches: bool = True,
) -> RunResult:
    """Ejecuta el ETL completo.

    Con `dry_run` se descarga y se transforma pero no se escribe en PostgreSQL:
    sirve para validar que el catalogo de metricas sigue casando con las
    columnas que publica FBref, sin tocar los datos.
    """
    settings = get_settings()
    leagues = leagues or settings.leagues
    seasons = seasons or settings.seasons

    logger.info("ETL iniciado", extra={"ligas": leagues, "temporadas": seasons, "dry_run": dry_run})
    _avisar_si_falta_poblacion(leagues)

    if dry_run:
        players = _prepare_players(leagues, seasons, use_cache) if load_players else None
        teams = _prepare_teams(leagues, seasons, use_cache) if load_teams else None
        shots = _prepare_shots(leagues, seasons) if load_shots else None
        partidos = _prepare_matches(leagues, seasons) if load_matches else None
        result = RunResult(
            player_rows=0 if players is None else len(players),
            team_rows=0 if teams is None else len(teams),
            shot_rows=0 if shots is None else len(shots),
            match_rows=0 if partidos is None else len(partidos),
        )
        # asdict y no __dict__: el dataclass usa slots, asi que no tiene __dict__ y
        # la simulacion terminaba siempre con AttributeError.
        logger.info("Simulacion terminada, no se ha escrito nada", extra=asdict(result))
        return result

    engine = get_engine()
    create_schema(engine)
    run_id = load.start_run(engine, leagues, seasons)

    try:
        player_rows = 0
        if load_players:
            players = _prepare_players(leagues, seasons, use_cache)
            player_rows = load.upsert(engine, player_season, transform.to_records(players))

        team_rows = 0
        if load_teams:
            teams = _prepare_teams(leagues, seasons, use_cache)
            team_rows = load.upsert(engine, team_season, transform.to_records(teams))

        shot_rows = 0
        if load_shots:
            shots = _prepare_shots(leagues, seasons)
            shot_rows = load.upsert(engine, shot_event, transform.to_records(shots))

        match_rows = 0
        if load_matches:
            partidos = _prepare_matches(leagues, seasons)
            match_rows = load.upsert(engine, player_match, transform.to_records(partidos))
    except Exception as error:
        load.finish_run(engine, run_id, status="failed", error=str(error))
        logger.exception("ETL fallido")
        raise
    else:
        load.finish_run(
            engine, run_id, status="success", player_rows=player_rows, team_rows=team_rows
        )
        logger.info(
            "ETL terminado",
            extra={
                "jugadores": player_rows,
                "equipos": team_rows,
                "tiros": shot_rows,
                "partidos": match_rows,
            },
        )
        return RunResult(
            player_rows=player_rows,
            team_rows=team_rows,
            shot_rows=shot_rows,
            match_rows=match_rows,
        )


def _prepare_shots(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """Descarga y transforma los tiros individuales.

    No pasa por el cache de `soccerdata` como los agregados: los tiros de una
    jornada no cambian una vez jugada, y los de la jornada nueva no estan en el
    cache de todas formas.
    """
    crudos = understat_source.read_shot_events(leagues, seasons)
    return transform.build_shot_frame(crudos)


def _prepare_matches(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    """Descarga y transforma las estadisticas por partido."""
    crudos = understat_source.read_player_match_stats(leagues, seasons)
    return transform.build_match_frame(crudos)


def _avisar_si_falta_poblacion(leagues: list[str]) -> None:
    """Avisa si la carga no cubre las cinco grandes ligas.

    Cargar solo LaLiga es legitimo para probar el ETL, pero rompe la premisa del
    producto: los percentiles se calculan contra las Big 5 porque con una sola
    liga la muestra por posicion se queda corta. Es un aviso, no un error: quien
    carga una liga suele saber lo que hace.
    """
    faltan = [liga for liga in BIG_5_LEAGUES if liga not in leagues]
    if faltan:
        logger.warning(
            "La carga no cubre las Big 5: los percentiles seran menos solidos",
            extra={"ligas_ausentes": faltan},
        )


def _prepare_players(
    leagues: list[str],
    seasons: list[str],
    use_cache: bool | None = None,
) -> pd.DataFrame:
    # Todo el catalogo viene de Understat: FBref sirve vacias sus tablas
    # avanzadas y unir ambas fuentes por nombre solo cruzaba el 62 % de los
    # jugadores, porque los equipos con acento y los nombres cortos no casan.
    understat = understat_source.read_player_season_stats(leagues, seasons)
    return transform.build_player_frame({}, PLAYER_METRICS, understat=understat)


def _prepare_teams(
    leagues: list[str],
    seasons: list[str],
    use_cache: bool | None = None,
) -> pd.DataFrame:
    crudo = understat_source.read_team_season_stats(leagues, seasons)
    if crudo.empty:
        return crudo

    # Las columnas llegan con los nombres de Understat: hay que traducirlas a
    # las del catalogo, que son las que existen como columnas en PostgreSQL.
    perspectivas = crudo["perspective"]
    traducido = transform.select_metrics(crudo, TEAM_METRICS, "team_season", source="understat")
    traducido["perspective"] = perspectivas
    return traducido.reset_index()


def inspect_columns(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
    destination: Path | None = None,
) -> Path:
    """Vuelca a JSON las columnas que FBref devuelve hoy, ya aplanadas.

    FBref renombra columnas de vez en cuando y eso rompe el catalogo. Este
    volcado permite comparar lo que espera `metrics.py` con lo que existe de
    verdad, sin tener que depurar a ciegas dentro del contenedor.
    """
    settings = get_settings()
    leagues = leagues or settings.leagues
    seasons = seasons or settings.seasons
    target = destination or Path(settings.soccerdata_dir).parent / "fbref_columns.json"

    # Cada tabla se pide por separado y se tolera que falle: el sentido de este
    # modo es descubrir en que se diferencia la realidad de lo que el catalogo
    # da por hecho, asi que morirse ante la primera diferencia lo vaciaria de
    # utilidad. Una tabla que la fuente no ofrece se anota como no disponible.
    disponible: dict[str, list[str]] = {}
    no_disponibles: dict[str, str] = {}
    for stat_type in stat_types(PLAYER_METRICS):
        try:
            frames = extract.read_player_stats((stat_type,), leagues, seasons)
        except Exception as error:  # noqa: BLE001 - se registra y se sigue
            no_disponibles[stat_type] = str(error)
            logger.warning(
                "Tabla no disponible en la fuente",
                extra={"stat_type": stat_type, "motivo": str(error)},
            )
            continue
        disponible[stat_type] = sorted(transform.flatten_columns(frames[stat_type]).columns)
    esperado = {metric.stat_type: [] for metric in PLAYER_METRICS}
    for metric in PLAYER_METRICS:
        esperado[metric.stat_type].append(metric.column)

    informe = {
        stat_type: {
            "tabla_disponible": stat_type not in no_disponibles,
            "motivo_si_no": no_disponibles.get(stat_type, ""),
            "disponibles": disponible.get(stat_type, []),
            "esperadas_por_el_catalogo": sorted(columns),
            "ausentes": sorted(set(columns) - set(disponible.get(stat_type, []))),
        }
        for stat_type, columns in esperado.items()
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Informe de columnas escrito", extra={"fichero": str(target)})
    return target
