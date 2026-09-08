"""Cache en memoria para los resultados de analisis.

Los percentiles y los clusters se calculan al vuelo en lugar de materializarse
en tablas. A esta escala (unos 3.000 jugadores por temporada) el calculo cuesta
poco, y evita el problema clasico de los percentiles precalculados: quedarse
obsoletos tras un re-scrapeo sin que nada lo indique.

La invalidacion no usa TTL. La clave incluye la version de los datos, es decir,
la marca de tiempo de la ultima carga correcta del ETL. Cuando el ETL vuelve a
cargar, la clave cambia y lo anterior deja de usarse. Un TTL siempre acaba
siendo demasiado corto (recalcula sin necesidad) o demasiado largo (sirve datos
viejos despues de una carga).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Suficiente para varias temporadas y variantes sin que la memoria del
# contenedor sea un problema.
MAX_ENTRIES = 16

_entries: OrderedDict[tuple, Any] = OrderedDict()


def get_or_compute(key: tuple, factory: Callable[[], Any]) -> Any:
    """Devuelve el valor cacheado o lo calcula y lo guarda.

    Las entradas mas antiguas se descartan primero, asi que las claves de
    versiones anteriores del dato desaparecen solas segun se usan las nuevas.
    """
    if key in _entries:
        _entries.move_to_end(key)
        logger.debug("Cache acertada", extra={"clave": str(key)})
        return _entries[key]

    logger.info("Cache fallada, se calcula", extra={"clave": str(key)})
    valor = factory()
    _entries[key] = valor
    _entries.move_to_end(key)
    while len(_entries) > MAX_ENTRIES:
        descartada, _ = _entries.popitem(last=False)
        logger.debug("Entrada descartada", extra={"clave": str(descartada)})
    return valor


def clear() -> None:
    """Vacia la cache. Se usa en los tests y al arrancar el proceso."""
    _entries.clear()


def size() -> int:
    """Numero de entradas vivas."""
    return len(_entries)
