"""Dependencias de FastAPI.

El acceso a datos se inyecta en lugar de importarse directamente en los
endpoints. Es lo que permite que los tests sustituyan PostgreSQL por DataFrames
en memoria con `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache

from futbol_analytics.api.repository import DataAccess, SqlDataAccess
from futbol_analytics.db import get_engine


@lru_cache(maxsize=1)
def _sql_data_access() -> SqlDataAccess:
    """Una sola instancia por proceso: el motor mantiene su pool de conexiones."""
    return SqlDataAccess(get_engine())


def get_data_access() -> DataAccess:
    """Acceso a datos para los endpoints."""
    return _sql_data_access()
