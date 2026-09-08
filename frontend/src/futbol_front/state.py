"""Cliente compartido y cacheo de las respuestas de la API.

El cacheo vive aqui y no en `client` para que el cliente HTTP se pueda testear
sin Streamlit. Se cachea la respuesta ya deserializada, que es barata de guardar
y evita repetir la peticion en cada interaccion con un filtro: Streamlit vuelve
a ejecutar el script entero con cada clic.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from futbol_front.client import ApiClient
from futbol_front.config import api_base_url, request_timeout

# Tiempo de vida de las respuestas cacheadas. Corto a proposito: la API ya
# invalida su propio calculo con la version de los datos, asi que este TTL solo
# evita repetir peticiones dentro de una misma sesion de trabajo.
TTL_SECONDS = 300


@st.cache_resource
def get_client() -> ApiClient:
    """Cliente unico por proceso."""
    return ApiClient(api_base_url(), timeout=request_timeout())


@st.cache_data(ttl=TTL_SECONDS)
def cached_catalog() -> dict[str, Any]:
    return get_client().catalog()


@st.cache_data(ttl=TTL_SECONDS)
def cached_templates() -> list[dict[str, Any]]:
    return get_client().templates()


@st.cache_data(ttl=TTL_SECONDS)
def cached_search(
    season: str,
    league: str | None,
    position_group: str | None,
    name: str | None,
) -> list[dict[str, Any]]:
    return get_client().search_players(
        season=season, league=league, position_group=position_group, name=name
    )


@st.cache_data(ttl=TTL_SECONDS)
def cached_profile(
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
def cached_styles(season: str, league: str | None, n_styles: int) -> dict[str, Any]:
    return get_client().team_styles(season=season, league=league, n_styles=n_styles)
