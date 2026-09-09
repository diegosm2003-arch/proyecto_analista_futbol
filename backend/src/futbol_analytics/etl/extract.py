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
from datetime import date
from typing import TYPE_CHECKING, Any

from futbol_analytics.config import BIG_5_LEAGUES, get_settings
from futbol_analytics.seasons import current_season

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


def needs_fresh_data(seasons: list[str], today: date | None = None) -> bool:
    """Si la carga incluye la temporada en curso.

    Es la decision que separa un ETL util de uno que parece funcionar: las
    estadisticas de una temporada cerrada no cambian nunca, pero las de la
    temporada en curso cambian cada jornada. Leerlas del cache devolveria
    siempre los datos de la primera descarga, y el ETL terminaria con exito
    cargando numeros congelados. Es el fallo mas dificil de detectar, porque no
    hay error que mirar.
    """
    return current_season(today) in set(seasons)


# Identificador de la pagina que FBref publica con las cinco grandes ligas
# juntas. soccerdata la reconoce y reparte cada fila a su liga real, asi que el
# resultado es indistinguible de scrapear las cinco por separado.
BIG5_COMBINED = "Big 5 European Leagues Combined"


def resolve_leagues(leagues: list[str]) -> list[str]:
    """Sustituye las cinco grandes ligas por la pagina combinada.

    FBref limita a una peticion cada 7 segundos, asi que pedir las cinco por
    separado multiplica por cinco el tiempo de una carga para obtener los mismos
    datos. El propio `soccerdata` avisa de ello si se le piden por separado.

    Solo se sustituye si estan las cinco: con cuatro no existe pagina combinada
    equivalente. Lo que no sean las Big 5 se conserva tal cual.
    """
    if not get_settings().use_combined_big5:
        return leagues
    if not set(BIG_5_LEAGUES).issubset(leagues):
        return leagues

    resto = [liga for liga in leagues if liga not in set(BIG_5_LEAGUES)]
    logger.info("Se usa la pagina combinada de las Big 5", extra={"ligas_extra": resto})
    return [BIG5_COMBINED, *resto]


def _fbref(leagues: list[str], seasons: list[str], *, no_cache: bool) -> Any:
    """Crea el lector de FBref.

    `soccerdata` decide donde cachear al importarse, leyendo `SOCCERDATA_DIR`.
    Por eso la variable se fija antes del import y el import es perezoso: con un
    import a nivel de modulo, el cache acabaria en el home del contenedor y se
    perderia al recrearlo.

    Con `no_cache` se descarga de nuevo, pero se sigue guardando (`no_store`
    queda en falso): el cache se refresca en lugar de desaparecer, asi que una
    ejecucion posterior con `--use-cache` sigue teniendo de donde tirar.
    """
    settings = get_settings()
    os.environ.setdefault("SOCCERDATA_DIR", settings.soccerdata_dir)

    import soccerdata

    return soccerdata.FBref(leagues=resolve_leagues(leagues), seasons=seasons, no_cache=no_cache)


def _resolve_cache(seasons: list[str], use_cache: bool | None) -> bool:
    """Decide si hay que ignorar el cache. Devuelve el valor de `no_cache`.

    `use_cache=None` deja decidir a la temporada, que es lo que quiere el
    proceso programado. Forzarlo a verdadero sirve para depurar sin volver a
    castigar a FBref, que limita a una peticion cada 7 segundos.
    """
    if use_cache is not None:
        return not use_cache
    return needs_fresh_data(seasons)


def read_player_stats(
    stat_types: tuple[str, ...],
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
    *,
    use_cache: bool | None = None,
) -> dict[str, pd.DataFrame]:
    """Descarga las tablas de jugadores indicadas.

    Devuelve un diccionario `stat_type -> DataFrame` con el indice original de
    `soccerdata` (liga, temporada, equipo, jugador).
    """
    settings = get_settings()
    temporadas = seasons or settings.seasons
    no_cache = _resolve_cache(temporadas, use_cache)
    logger.info(
        "Descargando jugadores",
        extra={"temporadas": temporadas, "ignora_cache": no_cache},
    )
    reader = _fbref(leagues or settings.leagues, temporadas, no_cache=no_cache)

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
    use_cache: bool | None = None,
) -> dict[str, pd.DataFrame]:
    """Descarga las tablas de equipos.

    Con `opponent=True` devuelve lo que los rivales le hacen al equipo, que es
    lo que permite derivar indicadores de presion como una PPDA aproximada.
    """
    settings = get_settings()
    temporadas = seasons or settings.seasons
    reader = _fbref(
        leagues or settings.leagues,
        temporadas,
        no_cache=_resolve_cache(temporadas, use_cache),
    )

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
