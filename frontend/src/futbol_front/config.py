"""Configuracion de la interfaz.

Solo necesita saber donde esta la API. No comparte codigo con el backend a
proposito: la interfaz habla HTTP y nada mas, asi que un cambio en el esquema de
datos o en el catalogo de metricas no puede romperla por la via de un import.
"""

from __future__ import annotations

import os

# Nombre del servicio de la API dentro de la red de Docker.
DEFAULT_API_BASE_URL = "http://backend:8000"
DEFAULT_TIMEOUT = 20


def api_base_url() -> str:
    """URL de la API. Unica dependencia de la interfaz con el resto."""
    return os.environ.get("API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


def request_timeout() -> int:
    """Segundos antes de dar una peticion por perdida."""
    try:
        return int(os.environ.get("API_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT
