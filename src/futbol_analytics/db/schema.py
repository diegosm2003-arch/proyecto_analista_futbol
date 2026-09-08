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
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
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
