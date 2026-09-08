"""Tests del logging estructurado."""

from __future__ import annotations

import json
import logging

from futbol_analytics.logging_config import JsonFormatter, configure_logging


def _record(**kwargs: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="futbol_analytics.etl",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="jugadores cargados: %d",
        args=(120,),
        exc_info=None,
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


def test_cada_linea_es_json_valido_con_los_campos_basicos() -> None:
    payload = json.loads(JsonFormatter(service="etl").format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "futbol_analytics.etl"
    assert payload["message"] == "jugadores cargados: 120"
    assert payload["service"] == "etl"
    assert "ts" in payload


def test_el_contexto_extra_se_incluye_aparte() -> None:
    payload = json.loads(JsonFormatter(service="etl").format(_record(liga="ESP-La Liga")))

    assert payload["context"] == {"liga": "ESP-La Liga"}


def test_sin_contexto_ni_servicio_no_se_anaden_esas_claves() -> None:
    payload = json.loads(JsonFormatter().format(_record()))

    assert "context" not in payload
    assert "service" not in payload


def test_configure_logging_deja_un_unico_handler_json(logging_intacto: None) -> None:
    configure_logging(service="api", level="warning")

    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
