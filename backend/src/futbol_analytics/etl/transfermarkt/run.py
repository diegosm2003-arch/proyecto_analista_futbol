"""Orquestacion de la carga de Transfermarkt.

    python -m futbol_analytics.etl.transfermarkt --season 2526
    python -m futbol_analytics.etl.transfermarkt --season 2526 --team Barcelona
    python -m futbol_analytics.etl.transfermarkt --pendientes

Un jugador que no se resuelve no frena al resto: se registra y se sigue. Con
cientos de jugadores por lote, parar en el primer nombre raro significaria no
cargar nunca nada.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict, dataclass

from futbol_analytics.config import get_settings
from futbol_analytics.db import create_schema, get_engine
from futbol_analytics.etl.transfermarkt import loader, matching, parser, squads
from futbol_analytics.etl.transfermarkt.client import (
    PlayerNotFoundError,
    TransfermarktClient,
    TransfermarktError,
)
from futbol_analytics.logging_config import configure_logging
from futbol_analytics.seasons import current_season

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    """Resumen de la carga."""

    considerados: int
    resueltos: int
    sin_resolver: int
    pendientes_de_revision: int
    valores_cargados: int
    fichajes_cargados: int
    fichas_cargadas: int = 0

    @property
    def tasa_resolucion(self) -> float:
        return self.resueltos / self.considerados if self.considerados else 0.0


def run(
    season: str | None = None,
    team: str | None = None,
    limit: int | None = None,
    league: str | None = None,
    refresh: bool = False,
) -> RunResult:
    """Resuelve identidades y carga ficha, valor de mercado y fichajes.

    El cruce se hace **por plantilla**: para cada equipo se pide de una vez la
    plantilla que Transfermarkt le atribuye y se comparan los nombres dentro de
    ella. Un jugador del Barcelona esta en la plantilla del Barcelona, asi que el
    problema deja de ser identificar a alguien entre medio millon de fichas y
    pasa a serlo entre veintitantas. Y de paso trae la ficha de cada uno sin una
    peticion extra.

    Si un equipo no se puede resolver asi (una liga fuera de las cinco grandes,
    un club que no aparece), se cae en la busqueda por nombre de siempre. Es
    peor, pero mejor que dejar al equipo sin datos.
    """
    ajustes = get_settings()
    temporada = season or current_season()
    motor = get_engine()
    create_schema(motor)

    cliente = TransfermarktClient()
    conocidos = loader.known_mappings(motor)

    # `refresh` ignora la ventana de frescura. Hace falta cuando cambia la forma
    # de cargar y no el dato: al arreglar el cruce de nombres de club, los
    # equipos afectados ya tenian tasaciones frescas y se habrian saltado hasta
    # el mes siguiente.
    jugadores = loader.pending_players(
        motor,
        temporada,
        0 if refresh else ajustes.transfermarkt_freshness_hours,
        limit=limit,
        team=team,
        league=league,
    )
    logger.info(
        "Jugadores a procesar",
        extra={
            "jugadores": len(jugadores),
            "temporada": temporada,
            "equipo": team,
            "liga": league,
        },
    )

    # Las plantillas se piden para TODOS los equipos de la temporada, no solo
    # para los que tienen jugadores pendientes: son 21 peticiones por liga y
    # traen la ficha de todo el mundo.
    todos = loader.season_players(motor, temporada, team=team, league=league)
    plantillas = _plantillas(cliente, {(j["league"], j["team"]) for j in todos})

    cruces, valores, fichajes, fichas = [], [], [], []
    sin_resolver = pendientes = 0
    a_cargar = {j["understat_id"] for j in jugadores}

    for jugador in todos:
        understat_id = jugador["understat_id"]
        nombre, equipo = jugador["player"], jugador["team"]
        plantilla = plantillas.get((jugador["league"], equipo), [])
        caro = understat_id in a_cargar

        cruce = _cruce_de(
            conocidos.get(understat_id),
            understat_id,
            nombre,
            equipo,
            plantilla,
            # La busqueda por nombre es una peticion por jugador, asi que solo se
            # intenta con quien toca actualizar. Para los demas basta con la
            # plantilla, que ya esta descargada.
            cliente if caro else None,
            ajustes,
        )
        if cruce is None:
            sin_resolver += caro
            continue
        if caro:
            cruces.append(cruce)

        if cruce.transfermarkt_id is None:
            sin_resolver += caro
            continue
        if not cruce.usable:
            # Cruce dudoso: se guarda para revisar, pero no se carga nada suyo.
            # Un valor de mercado de otra persona es peor que ninguno.
            pendientes += caro
            continue

        # La ficha sale de la plantilla ya descargada: no cuesta una peticion,
        # asi que se guarda siempre, toque actualizar el historico o no.
        ficha = _ficha_en(plantilla, cruce.transfermarkt_id)
        if ficha is not None:
            fichas.append(parser.parse_squad_player(ficha, understat_id))

        if not caro:
            continue

        try:
            valores.extend(
                parser.parse_market_value_history(
                    cliente.market_value(cruce.transfermarkt_id), understat_id
                )
            )
            fichajes.extend(
                parser.parse_transfers(cliente.transfers(cruce.transfermarkt_id), understat_id)
            )
        except PlayerNotFoundError:
            logger.warning("Transfermarkt no tiene datos", extra={"jugador": nombre})
        except TransfermarktError as error:
            # Un fallo con un jugador no puede tumbar el lote entero.
            logger.warning(
                "Fallo al leer un jugador", extra={"jugador": nombre, "motivo": str(error)}
            )

    loader.save_mapping(motor, cruces)
    cargadas_fichas = loader.load_profiles(motor, fichas)
    cargados_valores = loader.load_market_values(motor, valores)
    cargados_fichajes = loader.load_transfers(motor, fichajes)
    loader.refresh_team_values(motor, temporada)

    resultado = RunResult(
        considerados=len(jugadores),
        resueltos=sum(1 for c in cruces if c.usable),
        sin_resolver=sin_resolver,
        pendientes_de_revision=pendientes,
        valores_cargados=cargados_valores,
        fichajes_cargados=cargados_fichajes,
        fichas_cargadas=cargadas_fichas,
    )
    logger.info(
        "Transfermarkt cargado",
        extra={**asdict(resultado), "tasa_resolucion": round(resultado.tasa_resolucion, 3)},
    )
    return resultado


def _plantillas(
    cliente: TransfermarktClient,
    equipos: set[tuple[str, str]],
) -> dict[tuple[str, str], list[dict]]:
    """Plantilla de Transfermarkt para cada equipo, pedida una sola vez.

    Una liga entera son 1 peticion para los clubes mas 1 por club: veintiuna,
    frente a las mas de cuatrocientas busquedas por nombre de antes.
    """
    clubes_por_liga: dict[str, list[dict]] = {}
    resultado: dict[tuple[str, str], list[dict]] = {}

    for liga, equipo in sorted(equipos):
        competicion = squads.COMPETITION_IDS.get(liga)
        if competicion is None:
            continue

        if liga not in clubes_por_liga:
            try:
                clubes_por_liga[liga] = cliente.competition_clubs(competicion)
            except TransfermarktError as error:
                logger.warning(
                    "No se han podido leer los clubes de la liga",
                    extra={"liga": liga, "motivo": str(error)},
                )
                clubes_por_liga[liga] = []

        club = squads.match_club(equipo, clubes_por_liga[liga])
        if club is None:
            continue
        try:
            resultado[(liga, equipo)] = cliente.club_players(str(club["id"]))
        except TransfermarktError as error:
            logger.warning(
                "No se ha podido leer la plantilla",
                extra={"equipo": equipo, "motivo": str(error)},
            )

    logger.info("Plantillas resueltas", extra={"equipos": len(resultado)})
    return resultado


def _ficha_en(plantilla: list[dict], transfermarkt_id: str) -> dict | None:
    """Ficha de un jugador dentro de la plantilla ya descargada."""
    return next((j for j in plantilla if str(j.get("id")) == transfermarkt_id), None)


def _cruce_de(
    conocido: dict | None,
    understat_id: str,
    nombre: str,
    equipo: str,
    plantilla: list[dict],
    cliente: TransfermarktClient | None,
    ajustes,
) -> matching.Match | None:
    """Reutiliza el cruce guardado, o cruza contra la plantilla, o busca.

    Ese es el orden, y responde a lo que cuesta cada cosa. No se vuelve a buscar
    lo ya resuelto: son peticiones a una fuente ajena que no aportan nada. La
    plantilla ya esta descargada, asi que cruzar dentro de ella sale gratis y es
    mas fiable. La busqueda por nombre queda de ultimo recurso.
    """
    if conocido is not None:
        return matching.Match(
            understat_id=understat_id,
            player_name=conocido["player_name"],
            transfermarkt_id=conocido["transfermarkt_id"],
            match_method=conocido["match_method"],
            match_confidence=conocido["match_confidence"],
            reviewed=bool(conocido["reviewed"]),
        )

    if plantilla:
        cruce = squads.match_in_squad(
            understat_id, nombre, plantilla, ajustes.fuzzy_match_threshold
        )
        if cruce.transfermarkt_id is not None:
            return cruce
        # Sin cruce en su propia plantilla suele ser un jugador que ya se ha ido
        # o un canterano que Transfermarkt tiene en el filial. La busqueda por
        # nombre todavia puede encontrarlo.

    if cliente is None:
        # No toca gastar una peticion en este jugador.
        return None

    try:
        return matching.resolve(
            cliente, understat_id, nombre, equipo, ajustes.fuzzy_match_threshold
        )
    except TransfermarktError as error:
        logger.warning("Fallo al buscar", extra={"jugador": nombre, "motivo": str(error)})
        return None


def main(argv: list[str] | None = None) -> int:
    parser_cli = argparse.ArgumentParser(
        prog="futbol-analytics-transfermarkt",
        description="Carga valor de mercado y fichajes desde Transfermarkt.",
    )
    parser_cli.add_argument("--season", help="Temporada. Por defecto, la actual.")
    parser_cli.add_argument("--team", help="Limitar a un equipo, para probar sin cargar la liga.")
    parser_cli.add_argument("--league", help="Limitar a una liga.")
    parser_cli.add_argument(
        "--refresh",
        action="store_true",
        help="Reprocesar aunque el dato sea reciente. Para cuando cambia la forma de cargar.",
    )
    parser_cli.add_argument("--limit", type=int, help="Maximo de jugadores a procesar.")
    parser_cli.add_argument(
        "--pendientes",
        action="store_true",
        help="Lista los cruces que esperan revision manual y termina.",
    )
    args = parser_cli.parse_args(argv)

    configure_logging(service="transfermarkt")

    if args.pendientes:
        for fila in loader.unreviewed(get_engine()):
            logger.info(
                "Pendiente de revision",
                extra={
                    "jugador": fila["player_name"],
                    "transfermarkt_id": fila["transfermarkt_id"],
                    "confianza": fila["match_confidence"],
                },
            )
        return 0

    try:
        run(
            season=args.season,
            team=args.team,
            limit=args.limit,
            league=args.league,
            refresh=args.refresh,
        )
    except Exception:
        logger.exception("La carga de Transfermarkt ha terminado con error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
