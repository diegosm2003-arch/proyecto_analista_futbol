"""Carga de los datos de Transfermarkt en PostgreSQL.

Todo son upserts sobre la clave natural, igual que el resto del ETL: relanzar
actualiza y nunca duplica. Importa mas aqui que en ningun otro sitio, porque el
valor de mercado se revisa cada pocos meses y el historial se relee entero cada
vez que se consulta a un jugador.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, Table, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from futbol_analytics.db.schema import (
    player_id_mapping,
    player_market_value,
    player_profile,
    player_season,
    player_transfers,
    team_identity,
    team_market_value,
)
from futbol_analytics.etl.load import CHUNK_SIZE, upsert
from futbol_analytics.etl.transfermarkt.matching import Match

logger = logging.getLogger(__name__)

# Parte de la plantilla que hay que tener tasada para publicar el valor de un
# equipo. Por debajo, la suma enganaria mas de lo que informa.
MIN_COVERAGE = 0.7


def save_mapping(engine: Engine, matches: Sequence[Match]) -> int:
    """Guarda los cruces, resueltos o no.

    Tambien los que no encontraron nada: sin registrarlos se volveria a buscar
    lo mismo en cada ejecucion, gastando peticiones para llegar al mismo sitio.

    `reviewed` no se sobreescribe: si alguien ya confirmo un cruce a mano, una
    reejecucion no puede deshacerlo.
    """
    filas = [
        {
            "understat_id": m.understat_id,
            "transfermarkt_id": m.transfermarkt_id,
            "player_name": m.player_name,
            "match_method": m.match_method,
            "match_confidence": m.match_confidence,
        }
        for m in matches
    ]
    if not filas:
        return 0

    total = 0
    with engine.begin() as conexion:
        for inicio in range(0, len(filas), CHUNK_SIZE):
            lote = filas[inicio : inicio + CHUNK_SIZE]
            sentencia = pg_insert(player_id_mapping).values(lote)
            sentencia = sentencia.on_conflict_do_update(
                index_elements=["understat_id"],
                set_={
                    "transfermarkt_id": sentencia.excluded.transfermarkt_id,
                    "player_name": sentencia.excluded.player_name,
                    "match_method": sentencia.excluded.match_method,
                    "match_confidence": sentencia.excluded.match_confidence,
                    "updated_at": func.now(),
                },
            )
            conexion.execute(sentencia)
            total += len(lote)

    logger.info("Cruces guardados", extra={"filas": total})
    return total


def load_market_values(engine: Engine, rows: Sequence[dict]) -> int:
    """Historico de valor de mercado."""
    return upsert(engine, player_market_value, rows)


def load_transfers(engine: Engine, rows: Sequence[dict]) -> int:
    """Historial de fichajes."""
    return upsert(engine, player_transfers, rows)


def load_profiles(engine: Engine, rows: Sequence[dict]) -> int:
    """Fichas de jugador: edad, posicion concreta y contrato."""
    return upsert(engine, player_profile, rows)


def teams_of(engine: Engine, season: str, league: str | None = None) -> list[dict]:
    """Equipos con jugadores cargados en una temporada.

    Es por donde empieza la carga: se resuelve un club entero de una vez en
    lugar de ir jugador a jugador.
    """
    consulta = (
        select(player_season.c.league, player_season.c.team)
        .where(player_season.c.season == season)
        .group_by(player_season.c.league, player_season.c.team)
        .order_by(player_season.c.league, player_season.c.team)
    )
    if league is not None:
        consulta = consulta.where(player_season.c.league == league)
    with engine.connect() as conexion:
        return [dict(fila) for fila in conexion.execute(consulta).mappings()]


def load_team_identity(engine: Engine, rows: Sequence[dict]) -> int:
    """Guarda con que club de Transfermarkt se ha cruzado cada equipo.

    Sale gratis: el cruce ya se hace para descargar la plantilla, y guardarlo es
    lo que permite ensenar el escudo sin volver a preguntar por el.
    """
    return upsert(engine, team_identity, rows)


def season_players(
    engine: Engine,
    season: str,
    team: str | None = None,
    league: str | None = None,
) -> list[dict]:
    """Todos los jugadores cargados de una temporada.

    Distinto de `pending_players`, que solo devuelve a quien le falta el dato
    caro. La ficha viene incluida en la plantilla y no cuesta una peticion
    aparte, asi que no tiene sentido que la ventana de frescura —que existe para
    no repetir descargas caras— deje a un jugador sin edad ni posicion.
    """
    consulta = (
        select(
            player_season.c.understat_id,
            player_season.c.player,
            player_season.c.team,
            player_season.c.league,
        )
        .where(player_season.c.season == season, player_season.c.understat_id.is_not(None))
        .order_by(player_season.c.team, player_season.c.player)
    )
    if team is not None:
        consulta = consulta.where(player_season.c.team == team)
    if league is not None:
        consulta = consulta.where(player_season.c.league == league)

    with engine.connect() as conexion:
        return [dict(fila) for fila in conexion.execute(consulta).mappings()]


def pending_players(
    engine: Engine,
    season: str,
    freshness_hours: int,
    limit: int | None = None,
    team: str | None = None,
    league: str | None = None,
) -> list[dict]:
    """Jugadores cargados a los que les falta o les caduca el dato de mercado.

    Un valor de mercado se revisa cada pocos meses, asi que volver a pedir el
    historico completo de alguien consultado ayer es castigar a la fuente para
    nada. `freshness_hours` marca cuando merece la pena reintentarlo.
    """
    limite = datetime.now(UTC) - timedelta(hours=freshness_hours)

    reciente = (
        select(player_market_value.c.understat_id)
        .where(player_market_value.c.scraped_at > limite)
        .distinct()
        .scalar_subquery()
    )

    consulta = (
        select(
            player_season.c.understat_id,
            player_season.c.player,
            player_season.c.team,
            player_season.c.league,
        )
        .where(
            player_season.c.season == season,
            player_season.c.understat_id.is_not(None),
            player_season.c.understat_id.not_in(reciente),
        )
        .order_by(player_season.c.team, player_season.c.player)
    )
    if team is not None:
        consulta = consulta.where(player_season.c.team == team)
    if league is not None:
        consulta = consulta.where(player_season.c.league == league)
    if limit is not None:
        consulta = consulta.limit(limit)

    with engine.connect() as conexion:
        return [dict(fila) for fila in conexion.execute(consulta).mappings()]


def known_mappings(engine: Engine) -> dict[str, dict]:
    """Cruces ya resueltos, para no volver a buscarlos."""
    with engine.connect() as conexion:
        filas = conexion.execute(select(player_id_mapping)).mappings().all()
    return {fila["understat_id"]: dict(fila) for fila in filas}


def refresh_team_values(engine: Engine, season: str, min_coverage: float = MIN_COVERAGE) -> int:
    """Recalcula el valor de cada equipo sumando el de sus jugadores.

    Se deriva en lugar de scrapearse aparte para que siempre cuadre con la
    plantilla que tenemos cargada. Un valor traido de fuera incluiria a
    jugadores que no estan en nuestra base y no seria comparable con nada.

    Se usa la tasacion mas reciente de cada jugador, no la media historica: el
    valor de un equipo es lo que vale hoy.

    Solo se publica el equipo del que tengamos tasada la mayor parte de la
    plantilla. Una suma parcial no es un valor bajo, es un valor falso: al
    cargar solo el Barcelona aparecia el PSG valorado en 10 M porque uno de sus
    futbolistas habia jugado antes en el Barcelona. Comparar eso con otro equipo
    no significaria nada.
    """
    ultimo = (
        select(
            player_market_value.c.understat_id,
            func.max(player_market_value.c.valuation_date).label("fecha"),
        )
        .group_by(player_market_value.c.understat_id)
        .subquery()
    )

    valores = (
        select(
            player_season.c.league,
            player_season.c.season,
            player_season.c.team,
            func.max(ultimo.c.fecha).label("valuation_date"),
            func.sum(player_market_value.c.market_value_eur).label("market_value_eur"),
            func.count(player_market_value.c.market_value_eur).label("squad_size"),
        )
        .select_from(player_season)
        .join(ultimo, ultimo.c.understat_id == player_season.c.understat_id)
        .join(
            player_market_value,
            (player_market_value.c.understat_id == ultimo.c.understat_id)
            & (player_market_value.c.valuation_date == ultimo.c.fecha),
        )
        .where(player_season.c.season == season)
        .group_by(player_season.c.league, player_season.c.season, player_season.c.team)
    )

    plantillas = (
        select(
            player_season.c.team,
            func.count(player_season.c.player.distinct()).label("total"),
        )
        .where(player_season.c.season == season)
        .group_by(player_season.c.team)
    )

    with engine.connect() as conexion:
        filas = [dict(fila) for fila in conexion.execute(valores).mappings()]
        total_por_equipo = dict(conexion.execute(plantillas).all())

    completos, parciales = [], []
    for fila in filas:
        total = total_por_equipo.get(fila["team"], 0)
        fila["squad_total"] = total
        cobertura = fila["squad_size"] / total if total else 0.0
        (completos if cobertura >= min_coverage else parciales).append(fila)

    if parciales:
        logger.info(
            "Equipos sin plantilla suficiente para valorarlos",
            extra={"equipos": len(parciales), "cobertura_minima": min_coverage},
        )
    if not completos:
        logger.warning("Ningun equipo tiene tasada su plantilla")
        return 0
    return upsert(engine, team_market_value, completos)


def unreviewed(engine: Engine, table: Table = player_id_mapping) -> list[dict]:
    """Cruces pendientes de confirmar a mano."""
    consulta = (
        select(table)
        .where(table.c.reviewed.is_(False), table.c.transfermarkt_id.is_not(None))
        .order_by(table.c.match_confidence)
    )
    with engine.connect() as conexion:
        return [dict(fila) for fila in conexion.execute(consulta).mappings()]
