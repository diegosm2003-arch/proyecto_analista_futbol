"""Esquema de PostgreSQL.

Las columnas de metricas NO se escriben a mano: se generan desde el catalogo de
`futbol_analytics.metrics`. Anadir una metrica al catalogo anade su columna a la
tabla, y es imposible que esquema y catalogo se desincronicen.

Se usa SQLAlchemy Core (tablas), no el ORM. Aqui no hay logica de negocio por
fila: hay cargas masivas con upsert y consultas analiticas. El ORM solo anadiria
indireccion.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
    text,
)

from futbol_analytics.metrics import PLAYER_METRICS, TEAM_METRICS, Metric

# Convencion de nombres para indices y constraints: sin ella, PostgreSQL genera
# nombres automaticos que dificultan cualquier migracion posterior.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

_SQL_TYPES = {"int": Integer, "float": Float}


def metric_columns(metrics: tuple[Metric, ...]) -> list[Column]:
    """Convierte el catalogo en columnas.

    Todas son nullable: FBref no publica todas las estadisticas de todas las
    temporadas, y un hueco debe quedar como NULL y no como cero. Un cero seria
    una afirmacion falsa ("este jugador no dio ningun pase progresivo") en lugar
    de una ausencia de dato.
    """
    return [
        Column(metric.name, _SQL_TYPES[metric.dtype], nullable=True, comment=metric.label)
        for metric in metrics
    ]


player_season = Table(
    "player_season",
    metadata,
    # Clave natural. Un jugador que cambia de equipo a mitad de temporada tiene
    # una fila por etapa, que es lo correcto: su rendimiento en cada club es un
    # hecho distinto y mezclarlos ocultaria el cambio de contexto.
    Column("league", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("team", Text, primary_key=True),
    Column("player", Text, primary_key=True),
    # Identidad externa. Es la unica forma de cruzar con otras fuentes sin
    # depender del nombre, que se escribe distinto en cada web ("Abde Rebbach"
    # frente a "Abderrahmane Rebbach") y no distingue homonimos.
    Column(
        "understat_id",
        Text,
        nullable=True,
        comment="Identificador estable del jugador en Understat",
    ),
    # Identidad.
    Column("nation", Text, nullable=True),
    Column("age", Integer, nullable=True),
    Column("born", Integer, nullable=True),
    # Posicion. `position_raw` conserva lo que dijo FBref sin interpretar.
    Column("position_raw", Text, nullable=True, comment="Campo pos de FBref, sin tocar"),
    Column("position_group", String(2), nullable=True, comment="GK, DF, MF o FW"),
    # Nulo en la fase de datos. Lo rellena el clustering de roles de la fase 3:
    # FBref no publica la posicion detallada a nivel de temporada.
    Column(
        "detailed_position",
        Text,
        nullable=True,
        comment="Rol detallado, asignado por el clustering de la fase 3",
    ),
    *metric_columns(PLAYER_METRICS),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "position_group IS NULL OR position_group IN ('GK', 'DF', 'MF', 'FW')",
        name="position_group_valido",
    ),
    comment="Estadisticas de temporada por jugador y equipo. Totales, no por 90.",
)

# La consulta tipica de la API es "todos los jugadores de esta posicion en esta
# temporada" para construir la poblacion de percentiles.
Index(
    "ix_player_season_poblacion",
    player_season.c.season,
    player_season.c.position_group,
    player_season.c.minutes,
)


team_season = Table(
    "team_season",
    metadata,
    Column("league", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("team", Text, primary_key=True),
    # "for" = lo que hace el equipo; "against" = lo que le hacen los rivales.
    # Guardar ambas filas permite derivar indicadores de estilo que necesitan al
    # rival, como una PPDA aproximada.
    Column("perspective", String(7), primary_key=True),
    *metric_columns(TEAM_METRICS),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("perspective IN ('for', 'against')", name="perspective_valida"),
    comment="Estadisticas de temporada por equipo, a favor y en contra.",
)


# Trazabilidad de las cargas: sin esto, un dato raro en la interfaz no se puede
# atribuir a una ejecucion concreta del ETL.
etl_run = Table(
    "etl_run",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("status", Text, nullable=False, comment="running, success o failed"),
    Column("leagues", Text, nullable=False),
    Column("seasons", Text, nullable=False),
    Column("player_rows", Integer, nullable=True),
    Column("team_rows", Integer, nullable=True),
    Column("error", Text, nullable=True),
    comment="Registro de ejecuciones del ETL.",
)


# ---------------------------------------------------------------------------
# Transfermarkt: valor de mercado y fichajes
# ---------------------------------------------------------------------------
#
# Estas tablas se cuelgan del identificador de Understat y no de una clave
# entera propia. El motivo es que no existe una tabla de jugadores: la unidad
# del modelo es el jugador-temporada-equipo, porque el rendimiento de alguien
# traspasado en enero son dos hechos distintos. El valor de mercado, en cambio,
# es del jugador y no de su etapa en un club, asi que necesita una identidad que
# atraviese temporadas. `understat_id` es la unica que tenemos y es estable.

player_id_mapping = Table(
    "player_id_mapping",
    metadata,
    Column("understat_id", Text, primary_key=True),
    Column("transfermarkt_id", Text, nullable=True),
    Column("player_name", Text, nullable=False, comment="Nombre con el que se resolvio"),
    Column(
        "match_method",
        Text,
        nullable=False,
        comment="exact, fuzzy o manual",
    ),
    Column(
        "match_confidence",
        Float,
        nullable=True,
        comment="0 a 100. Por debajo del umbral no se usa hasta revisarlo",
    ),
    # Los cruces dudosos no se descartan: se guardan sin revisar y quedan fuera
    # de la carga hasta que alguien los confirme. Descartarlos perderia el
    # trabajo de haberlos encontrado; usarlos a ciegas contaminaria los datos.
    Column("reviewed", Boolean, nullable=False, server_default=text("false")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "match_method IN ('exact', 'fuzzy', 'history', 'squad', 'manual')",
        name="match_method_valido",
    ),
    comment="Puente entre el identificador de Understat y el de Transfermarkt.",
)


player_market_value = Table(
    "player_market_value",
    metadata,
    Column("understat_id", Text, primary_key=True),
    Column("valuation_date", Date, primary_key=True),
    Column("market_value_eur", Numeric(14, 2), nullable=True),
    Column("club_at_time", Text, nullable=True),
    Column("age_at_time", Integer, nullable=True),
    Column("scraped_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment="Historico de valor de mercado por jugador y fecha de tasacion.",
)

Index("ix_market_value_fecha", player_market_value.c.valuation_date)


team_identity = Table(
    "team_identity",
    metadata,
    Column("league", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("team", Text, primary_key=True),
    Column("transfermarkt_id", Text, nullable=True),
    Column("club_name", Text, nullable=True, comment="Nombre oficial en Transfermarkt"),
    Column("scraped_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment=(
        "Cruce de cada equipo nuestro con su club en Transfermarkt. Es lo que permite "
        "ensenar el escudo y enlazar la ficha del club."
    ),
)

player_profile = Table(
    "player_profile",
    metadata,
    Column("understat_id", Text, primary_key=True),
    Column("transfermarkt_id", Text, nullable=True),
    Column("player_name", Text, nullable=True),
    Column("date_of_birth", Date, nullable=True),
    Column("age", Integer, nullable=True),
    Column(
        "position",
        Text,
        nullable=True,
        comment="Posicion concreta de Transfermarkt (Centre-Back, Left Winger...)",
    ),
    Column("nationality", Text, nullable=True),
    Column("height_cm", Integer, nullable=True),
    Column("foot", Text, nullable=True),
    Column("joined_on", Date, nullable=True, comment="Fecha de llegada al club actual"),
    Column("signed_from", Text, nullable=True),
    Column("contract_until", Date, nullable=True),
    Column("scraped_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment=(
        "Ficha del jugador en Transfermarkt: edad, posicion concreta y contrato. "
        "Es el contexto que un percentil por si solo no da."
    ),
)

player_transfers = Table(
    "player_transfers",
    metadata,
    Column("understat_id", Text, primary_key=True),
    Column("transfer_date", Date, primary_key=True),
    Column("club_from", Text, primary_key=True),
    Column("club_to", Text, primary_key=True),
    Column("fee_eur", Numeric(14, 2), nullable=True),
    Column(
        "transfer_type",
        Text,
        nullable=True,
        comment="traspaso, cesion, fin_contrato o libre",
    ),
    Column("market_value_at_transfer_eur", Numeric(14, 2), nullable=True),
    Column("season", Text, nullable=True),
    Column("scraped_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment="Historial de fichajes por jugador.",
)


# El valor de un equipo se deriva de la suma de su plantilla y no se scrapea
# aparte: asi siempre cuadra con los jugadores que tenemos cargados, en lugar de
# ser una cifra ajena que puede incluir a quien no esta en nuestra base.
team_market_value = Table(
    "team_market_value",
    metadata,
    Column("league", Text, primary_key=True),
    Column("season", Text, primary_key=True),
    Column("team", Text, primary_key=True),
    Column("valuation_date", Date, primary_key=True),
    Column("market_value_eur", Numeric(14, 2), nullable=True),
    Column("squad_size", Integer, nullable=True, comment="Jugadores con valor conocido"),
    Column("squad_total", Integer, nullable=True, comment="Jugadores del equipo en la temporada"),
    Column("scraped_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment="Valor de mercado agregado por equipo, derivado de sus jugadores.",
)
