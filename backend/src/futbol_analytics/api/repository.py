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

from futbol_analytics.db import create_schema
from futbol_analytics.db.schema import (
    etl_run,
    player_market_value,
    player_profile,
    player_season,
    player_transfers,
    shot_event,
    team_identity,
    team_season,
)

logger = logging.getLogger(__name__)

# Valor de version cuando la base esta vacia. Forma parte de la clave de cache,
# asi que la primera carga correcta invalida lo cacheado durante el arranque.
NO_DATA_VERSION = "sin-datos"


class DataAccess(Protocol):
    """Lo que la API necesita de la base de datos.

    Es un Protocol y no una clase concreta para que los tests puedan inyectar
    DataFrames sin levantar PostgreSQL.
    """

    def ensure_schema(self) -> None:
        """Crea las tablas que falten."""

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

    def market(self, understat_id: str) -> dict:
        """Ficha, valor de mercado y carrera de un jugador en Transfermarkt."""

    def team_identities(self, season: str) -> dict[tuple[str, str], dict]:
        """Cruce de cada equipo con su club en Transfermarkt, por (liga, equipo)."""

    def squad_market(self, season: str, league: str, team: str) -> list[dict]:
        """Edad y ultimo valor de mercado de cada jugador de un equipo."""

    def ages(self, season: str) -> dict[str, int]:
        """Edad de cada jugador con ficha, por `understat_id`."""

    def shots(self, season: str, understat_id: str) -> list[dict]:
        """Tiros de un jugador en una temporada."""

    def shots_conceded(self, season: str, team: str) -> list[dict]:
        """Tiros que ha recibido un equipo, con donde se hicieron."""


class SqlDataAccess:
    """Implementacion sobre PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ensure_schema(self) -> None:
        """Crea las tablas que falten.

        Sin esto, una instalacion recien levantada no tiene esquema hasta que
        alguien lanza el ETL, y cualquier consulta falla con un error opaco. Es
        idempotente: arrancar mil veces no cambia nada.
        """
        create_schema(self._engine)

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

    def market(self, understat_id: str) -> dict:
        """Ficha, valor de mercado y carrera de un jugador.

        Va por `understat_id` y no por nombre porque es el unico identificador
        estable entre las dos fuentes: el nombre se escribe distinto en cada una
        y hay homonimos.
        """
        ficha = select(player_profile).where(player_profile.c.understat_id == understat_id)
        valores = (
            select(player_market_value)
            .where(player_market_value.c.understat_id == understat_id)
            .order_by(player_market_value.c.valuation_date)
        )
        carrera = (
            select(player_transfers)
            .where(player_transfers.c.understat_id == understat_id)
            .order_by(player_transfers.c.transfer_date)
        )
        with self._engine.connect() as conexion:
            fila = conexion.execute(ficha).mappings().first()
            return {
                "profile": dict(fila) if fila else None,
                "market_value": [dict(f) for f in conexion.execute(valores).mappings()],
                "transfers": [dict(f) for f in conexion.execute(carrera).mappings()],
            }

    def team_identities(self, season: str) -> dict[tuple[str, str], dict]:
        consulta = select(team_identity).where(team_identity.c.season == season)
        with self._engine.connect() as conexion:
            filas = conexion.execute(consulta).mappings().all()
        return {(f["league"], f["team"]): dict(f) for f in filas}

    def squad_market(self, season: str, league: str, team: str) -> list[dict]:
        """Edad y ultimo valor de mercado de cada jugador de un equipo.

        Se toma la tasacion mas reciente de cada uno, no la media: el valor de
        un jugador es lo que vale hoy.
        """
        ultimo = (
            select(
                player_market_value.c.understat_id,
                func.max(player_market_value.c.valuation_date).label("fecha"),
            )
            .group_by(player_market_value.c.understat_id)
            .subquery()
        )
        consulta = (
            select(
                player_season.c.player,
                player_profile.c.age,
                player_profile.c.position,
                player_market_value.c.market_value_eur,
            )
            .select_from(player_season)
            .join(player_profile, player_profile.c.understat_id == player_season.c.understat_id)
            .join(ultimo, ultimo.c.understat_id == player_season.c.understat_id)
            .join(
                player_market_value,
                (player_market_value.c.understat_id == ultimo.c.understat_id)
                & (player_market_value.c.valuation_date == ultimo.c.fecha),
            )
            .where(
                player_season.c.season == season,
                player_season.c.league == league,
                player_season.c.team == team,
            )
        )
        with self._engine.connect() as conexion:
            return [dict(fila) for fila in conexion.execute(consulta).mappings()]

    def ages(self, season: str) -> dict[str, int]:
        consulta = select(player_profile.c.understat_id, player_profile.c.age).where(
            player_profile.c.age.is_not(None)
        )
        with self._engine.connect() as conexion:
            return {fila[0]: int(fila[1]) for fila in conexion.execute(consulta)}

    def shots(self, season: str, understat_id: str) -> list[dict]:
        consulta = (
            select(shot_event)
            .where(
                shot_event.c.season == season,
                shot_event.c.understat_id == understat_id,
            )
            .order_by(shot_event.c.match_date, shot_event.c.minute)
        )
        with self._engine.connect() as conexion:
            return [dict(fila) for fila in conexion.execute(consulta).mappings()]

    def shots_conceded(self, season: str, team: str) -> list[dict]:
        """Tiros que ha recibido un equipo, con donde se hicieron.

        Se derivan del propio `shot_event` sin guardar el rival: los partidos de
        un equipo son aquellos en los que ha rematado, y los tiros concedidos
        son los del resto de equipos en esos mismos partidos. Guardar una
        columna de rival seria un dato duplicado que puede quedar desalineado.

        Las coordenadas de Understat van siempre desde la perspectiva de quien
        remata, asi que estos tiros se pintan en el mismo medio campo sin
        transformar nada: lo que se ve es desde donde le rematan.
        """
        suyos = (
            select(shot_event.c.game_id)
            .where(shot_event.c.season == season, shot_event.c.team == team)
            .distinct()
            .scalar_subquery()
        )
        consulta = (
            select(shot_event)
            .where(shot_event.c.game_id.in_(suyos), shot_event.c.team != team)
            .order_by(shot_event.c.match_date, shot_event.c.minute)
        )
        with self._engine.connect() as conexion:
            return [dict(fila) for fila in conexion.execute(consulta).mappings()]

    def _read(self, consulta) -> pd.DataFrame:
        with self._engine.connect() as conexion:
            frame = pd.read_sql(consulta, conexion)
        logger.debug("Consulta ejecutada", extra={"filas": len(frame)})
        return frame
