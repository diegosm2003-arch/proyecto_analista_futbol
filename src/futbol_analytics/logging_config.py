"""Logging estructurado (JSON) comun a todos los servicios.

Una linea = un objeto JSON. Asi las trazas del ETL, la API y el chat se pueden
filtrar y agregar con herramientas estandar en lugar de leerse a ojo. El campo
`service` distingue de que contenedor viene cada linea.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Atributos que `logging` pone en todos los registros. Cualquier otro atributo
# lo ha anadido quien llama (via `extra=...`) y se incluye en la salida.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Formatea cada registro como una unica linea JSON."""

    def __init__(self, service: str | None = None) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self.service:
            payload["service"] = self.service
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Contexto adicional pasado con logger.info("...", extra={"jugador": ...}).
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        if extras:
            payload["context"] = extras

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service: str, level: str | None = None) -> None:
    """Configura el logging raiz para un servicio.

    Se llama una vez, al arrancar cada proceso (ETL, API, Streamlit).
    """
    from futbol_analytics.config import get_settings

    resolved_level = (level or get_settings().log_level).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)
