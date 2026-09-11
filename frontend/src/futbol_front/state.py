"""Cliente compartido y cacheo de las respuestas de la API.

El cacheo vive aqui y no en `client` para que el cliente HTTP se pueda testear
sin Streamlit. Se cachea la respuesta ya deserializada, que es barata de guardar
y evita repetir la peticion en cada interaccion con un filtro: Streamlit vuelve
a ejecutar el script entero con cada clic.

**La invalidacion va por version de dato, no por tiempo**, igual que la cache de
la API. Un TTL a secas fallaba por los dos lados a la vez: con 5 minutos, la
interfaz seguia mostrando la jornada anterior durante 5 minutos despues de una
carga del ETL sin que nada lo indicara, y ademas tiraba todo lo cacheado cada 5
minutos aunque no hubiera cambiado nada, con lo que una sesion de trabajo de una
hora repetia doce veces las mismas peticiones.

Ahora la clave lleva la marca de tiempo de la ultima carga correcta. Si el ETL
carga, la clave cambia y la interfaz se actualiza en la siguiente interaccion;
si no carga, lo cacheado sirve durante toda la sesion. Lo unico que caduca por
tiempo es la sonda de version, que es una peticion de milisegundos.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from futbol_front.client import ApiClient, ApiError
from futbol_front.config import api_base_url, request_timeout

# Cada cuanto se vuelve a preguntar si hay datos nuevos. Es una peticion a
# /health, que no calcula nada.
VERSION_TTL_SECONDS = 30

# Vida maxima de una respuesta cacheada. Larga porque quien manda es la version
# del dato: esto solo evita que una pestana abierta toda la noche se quede con
# la respuesta de ayer si la sonda de version fallara.
TTL_SECONDS = 3600

# Version que se usa cuando la API no responde a la sonda. Constante a
# proposito: asi un fallo momentaneo de /health no invalida toda la cache ni
# hace que cada interaccion recalcule.
UNKNOWN_VERSION = "sin-version"


@st.cache_resource
def get_client() -> ApiClient:
    """Cliente unico por proceso."""
    return ApiClient(api_base_url(), timeout=request_timeout())


@st.cache_data(ttl=VERSION_TTL_SECONDS)
def cached_chat_status() -> dict[str, Any]:
    """Si el asistente esta disponible.

    Con la misma vida corta que `cached_health`: preguntarlo en cada pasada del
    script tumbaria un chat que ademas ya tarda por si solo, y a la vez hace
    falta saber pronto si Ollama se ha caido a media sesion.
    """
    return get_client().chat_status()


@st.cache_data(ttl=VERSION_TTL_SECONDS)
def cached_health() -> dict[str, Any]:
    """Estado de la API: version del dato y resultado de la ultima carga.

    Cacheada porque Streamlit reejecuta el script entero con cada clic, y esta
    respuesta la piden dos sitios a la vez: la sonda de version y el aviso de la
    barra lateral. Sin cache eran dos viajes de red por interaccion para
    preguntar algo que cambia dos veces por semana.

    Un fallo se propaga en lugar de cachearse: `st.cache_data` no guarda
    excepciones, asi que la interfaz reintenta en la siguiente pasada y el aviso
    de "API no disponible" desaparece en cuanto vuelve.
    """
    return get_client().health()


def data_version() -> str:
    """Marca de la ultima carga correcta del ETL.

    Es la clave de la que cuelga todo lo demas. Si la sonda falla se devuelve un
    valor fijo en lugar de propagar el error: que /health no conteste no deberia
    tumbar una pantalla cuyos datos ya estan cacheados.
    """
    try:
        return str(cached_health().get("data_version") or UNKNOWN_VERSION)
    except ApiError:
        return UNKNOWN_VERSION


def cached_catalog() -> dict[str, Any]:
    return _catalog(data_version())


def cached_templates() -> list[dict[str, Any]]:
    return _templates(data_version())


def cached_search(
    season: str,
    league: str | None,
    position_group: str | None,
    name: str | None,
    team: str | None = None,
) -> list[dict[str, Any]]:
    return _search(data_version(), season, league, position_group, name, team)


def cached_profile(
    player: str,
    season: str,
    team: str | None,
    basis: str,
    population: str,
) -> dict[str, Any]:
    return _profile(data_version(), player, season, team, basis, population)


def cached_market(player: str, season: str, team: str | None) -> dict[str, Any]:
    return _market(data_version(), player, season, team)


def cached_styles(season: str, league: str | None, n_styles: int) -> dict[str, Any]:
    return _styles(data_version(), season, league, n_styles)


def cached_insights(season: str) -> list[dict[str, Any]]:
    return _insights(data_version(), season)


def cached_teams(season: str, league: str | None) -> list[dict[str, Any]]:
    return _teams(data_version(), season, league)


def cached_conceded(team: str, season: str) -> dict[str, Any]:
    return _conceded(data_version(), team, season)


def cached_squad(team: str, season: str, league: str) -> list[dict[str, Any]]:
    return _squad(data_version(), team, season, league)


def cached_metrics() -> list[dict[str, Any]]:
    return _metrics(data_version())


def cached_scouting(**filtros: object) -> dict[str, Any]:
    # Los filtros se ordenan para que dos busquedas iguales compartan clave
    # de cache aunque los argumentos lleguen en otro orden.
    return _scouting(data_version(), tuple(sorted(filtros.items(), key=str)))


def cached_form(player: str, season: str, team: str | None) -> dict[str, Any]:
    return _form(data_version(), player, season, team)


def cached_shots(player: str, season: str, team: str | None) -> dict[str, Any]:
    return _shots(data_version(), player, season, team)


def cached_similar(
    player: str, season: str, team: str | None, basis: str, limit: int
) -> dict[str, Any]:
    return _similar(data_version(), player, season, team, basis, limit)


# Las funciones cacheadas de verdad. El primer parametro es la version del dato:
# no se usa dentro, solo forma parte de la clave. Van separadas de las de arriba
# para que quien las llama no tenga que acordarse de pasarla.


@st.cache_data(ttl=TTL_SECONDS)
def _catalog(version: str) -> dict[str, Any]:
    return get_client().catalog()


@st.cache_data(ttl=TTL_SECONDS)
def _templates(version: str) -> list[dict[str, Any]]:
    return get_client().templates()


@st.cache_data(ttl=TTL_SECONDS)
def _search(
    version: str,
    season: str,
    league: str | None,
    position_group: str | None,
    name: str | None,
    team: str | None = None,
) -> list[dict[str, Any]]:
    return get_client().search_players(
        season=season, league=league, team=team, position_group=position_group, name=name
    )


@st.cache_data(ttl=TTL_SECONDS)
def _profile(
    version: str,
    player: str,
    season: str,
    team: str | None,
    basis: str,
    population: str,
) -> dict[str, Any]:
    return get_client().player_profile(
        player=player, season=season, team=team, basis=basis, population=population
    )


@st.cache_data(ttl=TTL_SECONDS)
def _market(version: str, player: str, season: str, team: str | None) -> dict[str, Any]:
    return get_client().player_market(player=player, season=season, team=team)


@st.cache_data(ttl=TTL_SECONDS)
def _styles(version: str, season: str, league: str | None, n_styles: int) -> dict[str, Any]:
    return get_client().team_styles(season=season, league=league, n_styles=n_styles)


@st.cache_data(ttl=TTL_SECONDS)
def _similar(
    version: str, player: str, season: str, team: str | None, basis: str, limit: int
) -> dict[str, Any]:
    return get_client().player_similar(
        player=player, season=season, team=team, basis=basis, limit=limit
    )


@st.cache_data(ttl=TTL_SECONDS)
def _teams(version: str, season: str, league: str | None) -> list[dict[str, Any]]:
    return get_client().teams(season=season, league=league)


@st.cache_data(ttl=TTL_SECONDS)
def _squad(version: str, team: str, season: str, league: str) -> list[dict[str, Any]]:
    return get_client().squad(team=team, season=season, league=league)


@st.cache_data(ttl=TTL_SECONDS)
def _insights(version: str, season: str) -> list[dict[str, Any]]:
    return get_client().insights(season)


@st.cache_data(ttl=TTL_SECONDS)
def _shots(version: str, player: str, season: str, team: str | None) -> dict[str, Any]:
    return get_client().player_shots(player=player, season=season, team=team)


@st.cache_data(ttl=TTL_SECONDS)
def _conceded(version: str, team: str, season: str) -> dict[str, Any]:
    return get_client().shots_conceded(team=team, season=season)


@st.cache_data(ttl=TTL_SECONDS)
def _form(version: str, player: str, season: str, team: str | None) -> dict[str, Any]:
    return get_client().player_form(player=player, season=season, team=team)


@st.cache_data(ttl=TTL_SECONDS)
def _metrics(version: str) -> list[dict[str, Any]]:
    return get_client().metrics()


@st.cache_data(ttl=TTL_SECONDS)
def _scouting(version: str, filtros: tuple) -> dict[str, Any]:
    return get_client().scouting(**dict(filtros))
