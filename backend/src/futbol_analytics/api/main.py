"""Aplicacion FastAPI.

Es la unica via de acceso a los datos: ni Streamlit ni el chat tocan PostgreSQL.
Esa frontera es lo que permite cambiar el almacenamiento sin tocar la interfaz,
y lo que hace que el chat no pueda inventarse consultas.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from futbol_analytics import __version__
from futbol_analytics.api import cache
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.routers import meta, players, teams
from futbol_analytics.api.schemas import Health
from futbol_analytics.logging_config import configure_logging

logger = logging.getLogger(__name__)

DESCRIPTION = """
Percentiles por posicion y estilo de juego en las Big 5 ligas europeas.

Dos reglas que conviene tener presentes al leer las respuestas:

- **Los percentiles se calculan contra las Big 5 y se filtran despues.** Un
  percentil de LaLiga se ha comparado con toda Europa, no solo con LaLiga.
- **No todas las metricas tienen direccion.** Cuando `higher_is_better` es nulo,
  la metrica describe estilo y no calidad: no debe pintarse como buena ni mala.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Arranque y parada del servicio.

    El logging se configura aqui y no al importar el modulo: importar no debe
    tener efectos secundarios sobre el logging global.
    """
    configure_logging(service="api")
    cache.clear()
    logger.info("API arrancada", extra={"version": __version__})
    yield
    logger.info("API detenida")


app = FastAPI(
    title="Futbol Analytics API",
    version=__version__,
    summary="Percentiles por posicion y estilo de juego en las Big 5 ligas",
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.include_router(meta.router)
app.include_router(players.router)
app.include_router(teams.router)


@app.get("/health", tags=["infra"], summary="Comprobacion de vida")
def health(data: DataAccessDep) -> Health:
    """Estado del servicio y version de los datos cargados.

    `data_version` es la marca de la ultima carga correcta del ETL. Sirve para
    saber si lo que se esta viendo incluye el ultimo scraping, y es tambien lo
    que invalida la cache de los calculos.

    Si PostgreSQL no responde se sigue devolviendo 200 con la version en
    `desconocida`: el proceso esta vivo y sirviendo. Devolver un error aqui haria
    que Docker reiniciase el contenedor en bucle mientras la base arranca, que no
    arregla nada y ademas oculta la causa real.
    """
    try:
        version_datos = data.version()
        ultimas = data.last_runs(1)
        estado_etl = ultimas[0]["status"] if ultimas else None
    except SQLAlchemyError:
        logger.warning("PostgreSQL no responde al comprobar la version de los datos")
        version_datos, estado_etl = "desconocida", None
    return Health(
        status="ok",
        version=__version__,
        data_version=version_datos,
        last_etl_status=estado_etl,
    )
