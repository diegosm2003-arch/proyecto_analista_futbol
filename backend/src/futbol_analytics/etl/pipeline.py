"""Orquestacion del ETL: extraer, transformar, cargar.

Cada paso vive en su modulo; aqui solo se encadenan y se registra el resultado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from futbol_analytics.config import BIG_5_LEAGUES, get_settings
from futbol_analytics.db import create_schema, get_engine, player_season, team_season
from futbol_analytics.etl import extract, load, transform
from futbol_analytics.metrics import PLAYER_METRICS, TEAM_METRICS, stat_types

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Resumen de una ejecucion."""

    player_rows: int
    team_rows: int


def run(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    load_players: bool = True,
    load_teams: bool = True,
    dry_run: bool = False,
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
        players = _prepare_players(leagues, seasons) if load_players else None
        teams = _prepare_teams(leagues, seasons) if load_teams else None
        result = RunResult(
            player_rows=0 if players is None else len(players),
            team_rows=0 if teams is None else len(teams),
        )
        logger.info("Simulacion terminada, no se ha escrito nada", extra=result.__dict__)
        return result

    engine = get_engine()
    create_schema(engine)
    run_id = load.start_run(engine, leagues, seasons)

    try:
        player_rows = 0
        if load_players:
            players = _prepare_players(leagues, seasons)
            player_rows = load.upsert(engine, player_season, transform.to_records(players))

        team_rows = 0
        if load_teams:
            teams = _prepare_teams(leagues, seasons)
            team_rows = load.upsert(engine, team_season, transform.to_records(teams))
    except Exception as error:
        load.finish_run(engine, run_id, status="failed", error=str(error))
        logger.exception("ETL fallido")
        raise
    else:
        load.finish_run(
            engine, run_id, status="success", player_rows=player_rows, team_rows=team_rows
        )
        logger.info("ETL terminado", extra={"jugadores": player_rows, "equipos": team_rows})
        return RunResult(player_rows=player_rows, team_rows=team_rows)


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


def _prepare_players(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    frames = extract.read_player_stats(stat_types(PLAYER_METRICS), leagues, seasons)
    return transform.build_player_frame(frames, PLAYER_METRICS)


def _prepare_teams(leagues: list[str], seasons: list[str]) -> pd.DataFrame:
    needed = stat_types(TEAM_METRICS)
    frames_for = extract.read_team_stats(needed, leagues, seasons, opponent=False)
    frames_against = extract.read_team_stats(needed, leagues, seasons, opponent=True)
    return transform.build_team_frame(frames_for, frames_against, TEAM_METRICS)


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

    frames = extract.read_player_stats(stat_types(PLAYER_METRICS), leagues, seasons)
    disponible = {
        stat_type: sorted(transform.flatten_columns(frame).columns)
        for stat_type, frame in frames.items()
    }
    esperado = {metric.stat_type: [] for metric in PLAYER_METRICS}
    for metric in PLAYER_METRICS:
        esperado[metric.stat_type].append(metric.column)

    informe = {
        stat_type: {
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
