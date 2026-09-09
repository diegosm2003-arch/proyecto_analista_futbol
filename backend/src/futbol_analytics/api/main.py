"""Aplicacion FastAPI.

Es la unica via de acceso a los datos: ni Streamlit ni el chat tocan PostgreSQL.
Esa frontera es lo que permite cambiar el almacenamiento sin tocar la interfaz,
y lo que hace que el chat no pueda inventarse consultas.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from futbol_analytics import __version__
from futbol_analytics.api import cache
from futbol_analytics.api.dependencies import DataAccessDep, get_data_access
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
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Arranque y parada del servicio.

    El logging se configura aqui y no al importar el modulo: importar no debe
    tener efectos secundarios sobre el logging global.
    """
    configure_logging(service="api")
    cache.clear()
    _preparar_esquema(app)
    logger.info("API arrancada", extra={"version": __version__})
    yield
    logger.info("API detenida")


def _preparar_esquema(app: FastAPI) -> None:
    """Crea las tablas que falten al arrancar.

    Sin esto, una instalacion recien levantada no tiene esquema hasta que
    alguien lanza el ETL, y cualquier consulta falla. La interfaz saludaba con
    un error en lugar de decir que no hay datos, que es el peor primer contacto
    posible.

    El acceso a datos se resuelve respetando `dependency_overrides`, igual que
    en los endpoints: asi los tests, que lo sustituyen por DataFrames en
    memoria, no intentan conectar con PostgreSQL al arrancar la aplicacion.

    Si la base no responde se registra y se sigue: el proceso debe levantar
    igualmente para que `/health` pueda informar de que esta caida.
    """
    proveedor = app.dependency_overrides.get(get_data_access, get_data_access)
    try:
        proveedor().ensure_schema()
    except SQLAlchemyError:
        logger.warning("No se ha podido preparar el esquema: PostgreSQL no responde")


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


@app.exception_handler(SQLAlchemyError)
async def _error_de_base_de_datos(_: Request, error: SQLAlchemyError) -> JSONResponse:
    """Traduce un fallo de PostgreSQL a un 503 con un mensaje accionable.

    Sin esto sale un 500 opaco, que sugiere un error de programacion cuando lo
    que pasa es que la base no esta disponible. El 503 dice ademas que hacer.
    """
    logger.exception("Error de base de datos")
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "La base de datos no esta disponible. Comprueba que el servicio "
                "postgres esta levantado."
            )
        },
    )


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
