"""Motor de conexion a PostgreSQL."""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import Engine, create_engine

from futbol_analytics.config import get_settings
from futbol_analytics.db.schema import metadata

logger = logging.getLogger(__name__)


@lru_cache
def get_engine() -> Engine:
    """Motor unico por proceso.

    `pool_pre_ping` evita el fallo tipico al reanudar los contenedores: la
    conexion sigue en el pool pero PostgreSQL ya la ha cerrado.
    """
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def create_schema(engine: Engine | None = None) -> None:
    """Crea las tablas que falten.

    Suficiente para un proyecto de esta escala: el esquema evoluciona poco y
    anadir Alembic seria sobreingenieria. Si en el futuro hace falta cambiar
    columnas ya cargadas, se reevalua.
    """
    target = engine or get_engine()
    metadata.create_all(target, checkfirst=True)
    logger.info("Esquema verificado", extra={"tablas": sorted(metadata.tables)})
