"""Punto de entrada del ETL: `python -m futbol_analytics.etl`.

Es un job por lotes: se ejecuta, carga y termina. No es un servicio.

    python -m futbol_analytics.etl
    python -m futbol_analytics.etl --leagues "ESP-La Liga" --seasons 2526
    python -m futbol_analytics.etl --dry-run
    python -m futbol_analytics.etl --inspect

Codigos de salida: 0 correcto, 1 error, 3 ya habia una carga en marcha.
"""

from __future__ import annotations

import argparse
import logging
import sys

from futbol_analytics.config import get_settings
from futbol_analytics.etl import pipeline
from futbol_analytics.etl.load import EtlAlreadyRunningError
from futbol_analytics.logging_config import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="futbol-analytics-etl",
        description="Descarga estadisticas de FBref y las carga en PostgreSQL.",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        help="Ligas a procesar. Por defecto, las Big 5 configuradas en el entorno.",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        help="Temporadas en formato corto de soccerdata (2526 = 2025/26).",
    )
    parser.add_argument(
        "--only",
        choices=("players", "teams", "shots", "matches"),
        help="Cargar solo una parte: jugadores, equipos, tiros o partidos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Descarga y transforma pero no escribe en PostgreSQL.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Vuelca a JSON las columnas que FBref devuelve hoy y termina.",
    )

    cache = parser.add_mutually_exclusive_group()
    cache.add_argument(
        "--use-cache",
        dest="use_cache",
        action="store_true",
        default=None,
        help=(
            "Reutiliza el HTML ya descargado incluso para la temporada en curso. "
            "Util para depurar sin volver a castigar a FBref."
        ),
    )
    cache.add_argument(
        "--no-cache",
        dest="use_cache",
        action="store_false",
        help="Descarga de nuevo aunque la temporada este cerrada.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(service="etl")
    settings = get_settings()

    leagues = args.leagues or settings.leagues
    seasons = args.seasons or settings.seasons

    try:
        if args.inspect:
            pipeline.inspect_columns(leagues, seasons)
            return 0

        pipeline.run(
            leagues,
            seasons,
            # `--only X` significa "solo X": los otros dos quedan fuera.
            load_players=args.only in (None, "players"),
            load_teams=args.only in (None, "teams"),
            load_shots=args.only in (None, "shots"),
            load_matches=args.only in (None, "matches"),
            dry_run=args.dry_run,
            use_cache=args.use_cache,
        )
    except EtlAlreadyRunningError as error:
        # No es un fallo: es el candado haciendo su trabajo. Se distingue con un
        # codigo de salida propio para que un proceso programado pueda saltarse
        # el turno sin que parezca que algo se ha roto.
        logger.warning("Carga omitida", extra={"motivo": str(error)})
        return 3
    except Exception:
        # Con `logger.exception` y no `logger.error`: el modo --inspect no pasa
        # por pipeline.run, que es quien registraba la traza, asi que un fallo
        # ahi dejaba un mensaje sin causa y obligaba a depurar a ciegas. Es
        # justo el modo que se usa cuando algo va mal.
        logger.exception("El ETL ha terminado con error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
