"""Extraccion de FBref mediante `soccerdata`.

Unico modulo que toca la red. Se mantiene deliberadamente fino: descarga y
devuelve lo que FBref da, sin interpretarlo. Toda la limpieza vive en
`transform`, que se puede testear sin conexion.

Nota sobre el scraping: FBref limita la frecuencia de peticiones. `soccerdata`
cachea en disco, asi que la segunda ejecucion sobre la misma temporada es casi
instantanea. El cache vive en `data/`, fuera de Git.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from futbol_analytics.config import get_settings

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


def _fbref(leagues: list[str], seasons: list[str]) -> Any:
    """Crea el lector de FBref.

    `soccerdata` decide donde cachear al importarse, leyendo `SOCCERDATA_DIR`.
    Por eso la variable se fija antes del import y el import es perezoso: con un
    import a nivel de modulo, el cache acabaria en el home del contenedor y se
    perderia al recrearlo.
    """
    settings = get_settings()
    os.environ.setdefault("SOCCERDATA_DIR", settings.soccerdata_dir)

    import soccerdata

    return soccerdata.FBref(leagues=leagues, seasons=seasons)


def read_player_stats(
    stat_types: tuple[str, ...],
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Descarga las tablas de jugadores indicadas.

    Devuelve un diccionario `stat_type -> DataFrame` con el indice original de
    `soccerdata` (liga, temporada, equipo, jugador).
    """
    settings = get_settings()
    reader = _fbref(leagues or settings.leagues, seasons or settings.seasons)

    frames: dict[str, pd.DataFrame] = {}
    for stat_type in stat_types:
        logger.info("Descargando tabla de jugadores", extra={"stat_type": stat_type})
        frames[stat_type] = reader.read_player_season_stats(stat_type=stat_type)
        logger.info(
            "Tabla descargada",
            extra={"stat_type": stat_type, "filas": len(frames[stat_type])},
        )
    return frames


def read_team_stats(
    stat_types: tuple[str, ...],
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    opponent: bool = False,
) -> dict[str, pd.DataFrame]:
    """Descarga las tablas de equipos.

    Con `opponent=True` devuelve lo que los rivales le hacen al equipo, que es
    lo que permite derivar indicadores de presion como una PPDA aproximada.
    """
    settings = get_settings()
    reader = _fbref(leagues or settings.leagues, seasons or settings.seasons)

    frames: dict[str, pd.DataFrame] = {}
    for stat_type in stat_types:
        logger.info(
            "Descargando tabla de equipos",
            extra={"stat_type": stat_type, "perspectiva": "against" if opponent else "for"},
        )
        frames[stat_type] = reader.read_team_season_stats(
            stat_type=stat_type, opponent_stats=opponent
        )
    return frames
