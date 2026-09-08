"""Configuracion de la plataforma, leida de variables de entorno.

Todos los servicios (ETL, API, Streamlit) comparten este objeto. Nunca se
escriben credenciales en el codigo: los valores por defecto sirven para
desarrollo local y se sobreescriben con `.env` o con el entorno del contenedor.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Identificadores de liga tal y como los espera `soccerdata`.
BIG_5_LEAGUES = [
    "ESP-La Liga",
    "ENG-Premier League",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

# Liga sobre la que se enfoca la vista final del producto.
TARGET_LEAGUE = "ESP-La Liga"


class Settings(BaseSettings):
    """Ajustes de la plataforma."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- PostgreSQL ---
    postgres_user: str = "futbol"
    postgres_password: str = "futbol"
    postgres_db: str = "futbol"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # --- FastAPI ---
    # 0.0.0.0 es lo correcto dentro del contenedor: escucha en la red de Docker.
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # URL de la API. El frontend tiene su propia configuracion; esta la usara
    # el chat de la fase 6, que si vive en el backend.
    api_base_url: str = "http://backend:8000"

    # --- Ollama (opcional, fase final) ---
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:3b"

    # --- Datos ---
    # Poblacion de referencia para los percentiles: las Big 5, no solo LaLiga.
    # `NoDecode` es imprescindible: sin el, pydantic-settings intenta parsear
    # los tipos compuestos como JSON en el propio origen, ANTES de que corra el
    # validador de abajo, y `LEAGUES=ESP-La Liga,...` revienta el arranque.
    leagues: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(BIG_5_LEAGUES))
    # Temporadas en formato corto de soccerdata: "2425" = 2024/25.
    seasons: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["2425", "2526"])
    # Directorio de cache del scraping (soccerdata). Fuera de Git, en el
    # volumen de datos: sin cache, cada ejecucion vuelve a descargar FBref.
    soccerdata_dir: str = "/app/data/soccerdata"
    # Minutos minimos para que un jugador entre en la poblacion de percentiles.
    # Por debajo de este umbral las metricas por 90 son ruido, no senal.
    min_minutes: int = 450

    # --- Observabilidad ---
    log_level: str = "INFO"

    @field_validator("leagues", "seasons", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Permite pasar listas por entorno como texto separado por comas.

        `LEAGUES="ESP-La Liga,ENG-Premier League"` es mas comodo en un `.env`
        que el JSON que pydantic espera por defecto para tipos compuestos.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def database_url(self) -> str:
        """Cadena de conexion SQLAlchemy (driver psycopg 3)."""
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes, cacheados para no releer el entorno en cada uso."""
    return Settings()
