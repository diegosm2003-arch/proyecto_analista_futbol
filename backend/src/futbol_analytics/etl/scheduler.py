"""Planificador del ETL: `python -m futbol_analytics.etl.scheduler`.

Ejecuta la carga de forma periodica sin salir del contenedor. Se usa un
planificador en Python y no el `cron` del sistema por cuatro razones concretas
con esta imagen:

- `python:3.11-slim` no trae `cron`, habria que anadir una capa de `apt`.
- El contenedor corre como usuario sin privilegios, y `cron` espera root.
- `cron` no escribe en stdout, asi que el logging estructurado en JSON que
  recoge Docker se perderia justo en las ejecuciones que nadie mira.
- `cron` no hereda el entorno del contenedor. Es el fallo clasico: funciona
  lanzado a mano y falla programado, porque le faltan POSTGRES_HOST o
  SOCCERDATA_DIR.

Un proceso Python resuelve los cuatro sin anadir nada al sistema.

**Cadencia.** Por defecto martes y jueves por la manana: las estadisticas de
temporada solo cambian cuando se juega una jornada, y LaLiga juega de viernes a
lunes con alguna jornada entre semana. Una carga diaria multiplicaria por siete
las peticiones a Understat para uno o dos cambios reales.

**La temporada se resuelve en cada ejecucion, no al arrancar.** Es lo que
distingue a este proceso de un comando: vive semanas y cruza el cambio de
temporada de julio. Resolviendola al arrancar, un planificador levantado en
junio seguiria cargando la temporada anterior en septiembre e informando
"success" cada martes, sin ningun error que mirar.

**Dos cargas con ritmos distintos.** Las estadisticas siguen a la jornada;
el valor de mercado, no. Transfermarkt revisa sus tasaciones unas pocas veces al
ano, asi que su carga va los sabados y no con el resto: un dato que cambia
trimestralmente no gana nada consultandose dos veces por semana.

El dia distinto tampoco es casual. La carga de Transfermarkt lee `player_season`
para saber a quien buscar, y leer esa tabla mientras el ETL la reescribe daria
una plantilla a medias.

**Cuidado con los dias**: APScheduler numera 0 = lunes, mientras que el cron de
toda la vida usa 0 = domingo. Por eso la expresion usa nombres (`tue,thu`) y no
numeros: con numeros, la misma expresion carga dos dias distintos segun quien la
lea.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from futbol_analytics.config import get_settings, seasons_to_load
from futbol_analytics.etl import pipeline
from futbol_analytics.etl.load import EtlAlreadyRunningError
from futbol_analytics.etl.transfermarkt import run as transfermarkt
from futbol_analytics.logging_config import configure_logging

logger = logging.getLogger(__name__)

JOB_ID = "etl"
TRANSFERMARKT_JOB_ID = "transfermarkt"


def run_once() -> None:
    """Una ejecucion del ETL, con los errores contenidos.

    El planificador nunca debe morir por un fallo de carga: FBref puede estar
    caido un martes y funcionar el jueves. Se registra y se sigue.
    """
    ajustes = get_settings()
    # La temporada se resuelve AQUI, no al arrancar el proceso: este
    # planificador vive semanas y cruza el cambio de temporada en julio.
    temporadas = seasons_to_load(ajustes)
    try:
        resultado = pipeline.run(ajustes.leagues, temporadas)
    except EtlAlreadyRunningError as error:
        # El candado ha hecho su trabajo: hay otra carga viva. No es un fallo.
        logger.warning("Carga omitida", extra={"motivo": str(error)})
    except Exception:
        logger.exception("La carga programada ha fallado")
    else:
        logger.info(
            "Carga programada terminada",
            extra={
                "temporadas": temporadas,
                "jugadores": resultado.player_rows,
                "equipos": resultado.team_rows,
            },
        )


def run_transfermarkt_once() -> None:
    """Una carga de valor de mercado y fichajes, con los errores contenidos.

    Igual que el ETL: que Transfermarkt no responda un sabado no puede dejar sin
    planificador a la carga de estadisticas del martes.
    """
    try:
        resultado = transfermarkt.run()
    except Exception:
        logger.exception("La carga de Transfermarkt ha fallado")
    else:
        logger.info(
            "Transfermarkt programado terminado",
            extra={
                "resueltos": resultado.resueltos,
                "pendientes_de_revision": resultado.pendientes_de_revision,
                "valores": resultado.valores_cargados,
                "fichajes": resultado.fichajes_cargados,
            },
        )


def build_scheduler() -> BlockingScheduler:
    """Configura el planificador a partir del entorno."""
    ajustes = get_settings()
    planificador = BlockingScheduler(timezone=ajustes.schedule_timezone)

    planificador.add_job(
        run_once,
        trigger=CronTrigger.from_crontab(ajustes.etl_schedule, timezone=ajustes.schedule_timezone),
        id=JOB_ID,
        name="Carga de Understat",
        # Una sola ejecucion a la vez dentro de este proceso. El candado sobre
        # `etl_run` cubre el caso de dos contenedores; esto cubre el de una
        # carga que se alarga mas que el intervalo.
        max_instances=1,
        # Si el contenedor ha estado parado y se han acumulado disparos, se
        # ejecuta uno solo: cargar cuatro veces seguidas los mismos datos no
        # aporta nada y castiga a FBref.
        coalesce=True,
        misfire_grace_time=3600,
    )

    if ajustes.transfermarkt_schedule:
        planificador.add_job(
            run_transfermarkt_once,
            trigger=CronTrigger.from_crontab(
                ajustes.transfermarkt_schedule, timezone=ajustes.schedule_timezone
            ),
            id=TRANSFERMARKT_JOB_ID,
            name="Valor de mercado y fichajes",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return planificador


def main() -> int:
    configure_logging(service="scheduler")
    ajustes = get_settings()

    planificador = build_scheduler()
    logger.info(
        "Planificador iniciado",
        extra={
            "cron": ajustes.etl_schedule,
            "cron_transfermarkt": ajustes.transfermarkt_schedule,
            "zona_horaria": ajustes.schedule_timezone,
            "ligas": ajustes.leagues,
            "temporadas": seasons_to_load(ajustes),
            "carga_al_arrancar": ajustes.etl_run_on_start,
        },
    )

    if ajustes.etl_run_on_start:
        # Util la primera vez que se levanta la plataforma: evita esperar al
        # martes para tener datos.
        logger.info("Carga inicial al arrancar")
        run_once()
        if ajustes.transfermarkt_schedule:
            # Despues del ETL y no en paralelo: Transfermarkt necesita saber que
            # jugadores hay en la temporada, y eso lo acaba de escribir la carga
            # anterior.
            run_transfermarkt_once()

    try:
        planificador.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Planificador detenido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
