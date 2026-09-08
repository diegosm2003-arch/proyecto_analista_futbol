"""Servicios de la API: unen datos y analisis, y cachean el resultado.

Aqui vive el orden correcto de las operaciones, que es lo que hace que los
numeros signifiquen algo:

1. Se traen TODOS los jugadores de la temporada (las Big 5, no solo LaLiga).
2. Se asignan roles con el clustering.
3. Se calculan percentiles contra esa poblacion completa.
4. **Solo entonces** se filtra por liga, equipo o posicion.

Invertir el paso 4 con el 3 no da un error: da un numero que parece bueno y no
lo es.
"""

from __future__ import annotations

import logging

import pandas as pd

from futbol_analytics.analysis import features, percentiles, roles, style
from futbol_analytics.api import cache
from futbol_analytics.api.repository import DataAccess
from futbol_analytics.config import get_settings
from futbol_analytics.metrics import PLAYER_METRICS

logger = logging.getLogger(__name__)

# Como se define la poblacion contra la que se compara a un jugador.
POPULATION_POSITION = "position"
POPULATION_ROLE = "role"
POPULATIONS = (POPULATION_POSITION, POPULATION_ROLE)

_POPULATION_KEYS = {
    # Por defecto. Poblacion amplia y estable.
    POPULATION_POSITION: ("season", "position_group"),
    # Comparacion mas fina: un central contra centrales, no contra laterales.
    # La poblacion se reduce a un cuarto, asi que los extremos son mas ruidosos.
    POPULATION_ROLE: ("season", "detailed_position"),
}


class NoDataError(RuntimeError):
    """No hay datos cargados para lo que se pide."""


def enriched_players(data: DataAccess, season: str) -> pd.DataFrame:
    """Jugadores de una temporada con su rol asignado.

    El rol se calcula aqui y no en el ETL porque depende de toda la poblacion:
    no se puede decidir si un defensa es central o lateral mirandolo solo a el.
    """
    clave = ("players", season, data.version())
    return cache.get_or_compute(clave, lambda: _build_players(data, season))


def player_percentiles(
    data: DataAccess,
    season: str,
    population: str = POPULATION_POSITION,
) -> pd.DataFrame:
    """Percentiles de todos los jugadores de una temporada.

    Raises:
        NoDataError: Si la temporada no tiene datos.
        ValueError: Si la poblacion pedida no existe.
    """
    if population not in _POPULATION_KEYS:
        raise ValueError(f"Poblacion desconocida: {population!r}. Usa una de {POPULATIONS}.")

    clave = ("percentiles", season, population, data.version())
    return cache.get_or_compute(clave, lambda: _build_percentiles(data, season, population))


def team_styles(data: DataAccess, season: str, n_styles: int) -> style.StyleResult:
    """Estilos de juego de los equipos de una temporada."""
    clave = ("styles", season, n_styles, data.version())
    return cache.get_or_compute(clave, lambda: _build_styles(data, season, n_styles))


def _build_players(data: DataAccess, season: str) -> pd.DataFrame:
    jugadores = data.players(season)
    if jugadores.empty:
        raise NoDataError(f"No hay jugadores cargados para la temporada {season!r}.")

    # El clustering se hace sobre la poblacion que cumple el umbral de minutos:
    # las proporciones de un jugador con 100 minutos son inestables y
    # deformarian los centroides de los roles.
    ajustes = get_settings()
    umbral = features.effective_min_minutes(
        jugadores, ajustes.min_minutes, ajustes.min_minutes_ratio
    )
    elegibles = features.eligible(jugadores, umbral)
    con_rol = roles.assign_all_roles(elegibles)

    # Los que no llegan al umbral se conservan sin rol: existen, aunque no se
    # les pueda comparar.
    claves = ["league", "season", "team", "player"]
    descartados = jugadores.merge(con_rol[claves], on=claves, how="left", indicator=True)
    descartados = descartados[descartados["_merge"] == "left_only"].drop(columns=["_merge"])
    descartados = descartados.assign(detailed_position=None)

    return pd.concat([con_rol, descartados], ignore_index=True)


def _build_percentiles(data: DataAccess, season: str, population: str) -> pd.DataFrame:
    jugadores = enriched_players(data, season)
    equipos = data.teams(season)

    posesion = None
    if not equipos.empty:
        try:
            posesion = features.team_possession(equipos)
        except KeyError:
            # Sin posesion se pierde la version ajustada, no todo el analisis.
            logger.warning("No se ha podido calcular la posesion de los equipos")

    ajustes = get_settings()
    umbral = features.effective_min_minutes(
        jugadores, ajustes.min_minutes, ajustes.min_minutes_ratio
    )
    resultado = percentiles.compute(
        jugadores,
        PLAYER_METRICS,
        min_minutes=umbral,
        possession=posesion,
        population_keys=_POPULATION_KEYS[population],
    )
    if resultado.empty:
        raise NoDataError(
            f"Ningun jugador de la temporada {season!r} supera los {umbral} minutos minimos."
        )
    return resultado


def _build_styles(data: DataAccess, season: str, n_styles: int) -> style.StyleResult:
    equipos = data.teams(season)
    if equipos.empty:
        raise NoDataError(f"No hay equipos cargados para la temporada {season!r}.")
    try:
        return style.cluster_styles(equipos, n_styles=n_styles)
    except ValueError as error:
        raise NoDataError(str(error)) from error


def population_context(data: DataAccess, season: str) -> dict[str, int]:
    """Cuanta poblacion sostiene los percentiles de una temporada.

    Se devuelve al cliente porque cambia como hay que leer el numero: un
    percentil calculado sobre una sola liga, o sobre una temporada de la que van
    cuatro jornadas, no vale lo mismo que uno de una temporada cerrada de las
    Big 5.
    """
    jugadores = enriched_players(data, season)
    ajustes = get_settings()
    return {
        "leagues": int(jugadores["league"].nunique()),
        "min_minutes": features.effective_min_minutes(
            jugadores, ajustes.min_minutes, ajustes.min_minutes_ratio
        ),
        "configured_min_minutes": ajustes.min_minutes,
    }


def population_column(population: str) -> str:
    """Columna que define la poblacion de comparacion."""
    return _POPULATION_KEYS[population][1]


def population_size(frame: pd.DataFrame, season: str, column: str, value: str | None) -> int:
    """Cuantos jugadores forman la poblacion de comparacion.

    Se devuelve junto al percentil a proposito: un percentil calculado contra 40
    jugadores y otro contra 400 no valen lo mismo, y quien lee el grafico tiene
    derecho a saberlo.
    """
    if frame.empty or value is None or column not in frame.columns:
        return 0
    poblacion = frame[(frame["season"] == season) & (frame[column] == value)]
    return int(poblacion[["player", "team"]].drop_duplicates().shape[0])
