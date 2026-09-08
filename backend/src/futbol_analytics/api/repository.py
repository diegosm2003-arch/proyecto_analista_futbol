"""Acceso a PostgreSQL desde la API.

Es la unica capa que ejecuta SQL. Devuelve DataFrames en crudo; interpretarlos
es cosa de `services`, que a su vez delega el analisis en `analysis`. Esa
separacion es la que permite testear la API sin base de datos: basta con
sustituir el `DataAccess`.
"""

from __future__ import annotations

import logging
from typing import Protocol

import pandas as pd
from sqlalchemy import Engine, distinct, func, select

from futbol_analytics.db.schema import etl_run, player_season, team_season

logger = logging.getLogger(__name__)

# Valor de version cuando la base esta vacia. Forma parte de la clave de cache,
# asi que la primera carga correcta invalida lo cacheado durante el arranque.
NO_DATA_VERSION = "sin-datos"


class DataAccess(Protocol):
    """Lo que la API necesita de la base de datos.

    Es un Protocol y no una clase concreta para que los tests puedan inyectar
    DataFrames sin levantar PostgreSQL.
    """

    def version(self) -> str:
        """Identificador de la ultima carga correcta del ETL."""

    def seasons(self) -> list[str]:
        """Temporadas con datos."""

    def leagues(self) -> list[str]:
        """Ligas con datos."""

    def players(self, season: str) -> pd.DataFrame:
        """Filas de `player_season` de una temporada, con totales."""

    def teams(self, season: str) -> pd.DataFrame:
        """Filas de `team_season` de una temporada, ambas perspectivas."""

    def last_runs(self, limit: int) -> list[dict]:
        """Ultimas ejecuciones del ETL, de la mas reciente a la mas antigua."""


class SqlDataAccess:
    """Implementacion sobre PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def version(self) -> str:
        """Marca de tiempo de la ultima carga correcta.

        Se usa como parte de la clave de cache: cuando el ETL vuelve a cargar,
        la clave cambia y lo cacheado se descarta solo. Evita tener que elegir
        un TTL, que siempre es o demasiado corto o demasiado largo.
        """
        consulta = select(func.max(etl_run.c.finished_at)).where(etl_run.c.status == "success")
        with self._engine.connect() as conexion:
            ultima = conexion.execute(consulta).scalar_one_or_none()
        return ultima.isoformat() if ultima is not None else NO_DATA_VERSION

    def seasons(self) -> list[str]:
        consulta = select(distinct(player_season.c.season)).order_by(player_season.c.season)
        with self._engine.connect() as conexion:
            return [fila[0] for fila in conexion.execute(consulta)]

    def leagues(self) -> list[str]:
        consulta = select(distinct(player_season.c.league)).order_by(player_season.c.league)
        with self._engine.connect() as conexion:
            return [fila[0] for fila in conexion.execute(consulta)]

    def players(self, season: str) -> pd.DataFrame:
        # Se traen TODAS las ligas de la temporada, no solo LaLiga: la poblacion
        # de referencia de los percentiles son las Big 5. Filtrar por liga aqui
        # romperia el calculo, no solo la vista.
        consulta = select(player_season).where(player_season.c.season == season)
        return self._read(consulta)

    def teams(self, season: str) -> pd.DataFrame:
        consulta = select(team_season).where(team_season.c.season == season)
        return self._read(consulta)

    def last_runs(self, limit: int = 5) -> list[dict]:
        """Ultimas ejecuciones del ETL.

        Se expone porque `data_version` sola enmascara un problema: si la carga
        programada falla, la fecha de la ultima carga correcta sigue ahi y la
        interfaz seguiria mostrandola tan tranquila. Hay que poder ver que el
        ultimo intento no salio bien.
        """
        consulta = select(etl_run).order_by(etl_run.c.started_at.desc()).limit(max(1, int(limit)))
        with self._engine.connect() as conexion:
            filas = conexion.execute(consulta).mappings().all()
        return [dict(fila) for fila in filas]

    def _read(self, consulta) -> pd.DataFrame:
        with self._engine.connect() as conexion:
            frame = pd.read_sql(consulta, conexion)
        logger.debug("Consulta ejecutada", extra={"filas": len(frame)})
        return frame
