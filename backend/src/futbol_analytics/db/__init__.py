"""Acceso a PostgreSQL: esquema y motor de conexion.

Lo comparten el ETL (que escribe) y la API (que lee). Streamlit no importa
este paquete: su unica via a los datos es la API.
"""

from futbol_analytics.db.engine import create_schema, get_engine
from futbol_analytics.db.schema import etl_run, metadata, player_season, team_season

__all__ = [
    "create_schema",
    "etl_run",
    "get_engine",
    "metadata",
    "player_season",
    "team_season",
]
