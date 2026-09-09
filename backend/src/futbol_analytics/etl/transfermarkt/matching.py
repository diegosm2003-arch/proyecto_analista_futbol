"""Cruce de identidades entre Understat y Transfermarkt.

Es la parte dificil de esta integracion. Las dos fuentes usan identificadores
propios y no comparten ninguno, asi que hay que cruzar por nombre. Y el nombre
es un identificador pesimo en futbol: se escribe distinto en cada web
("Abde Rebbach" frente a "Abderrahmane Rebbach"), lleva acentos que unas fuentes
conservan y otras no, y hay homonimos.

Tres decisiones contienen ese riesgo:

**El club desempata, y cuando no basta se mira la carrera.** Es la defensa
contra el peor error posible: confundir a dos jugadores distintos con el mismo
nombre. Pero el club que devuelve la busqueda es el ACTUAL, y nosotros cargamos
temporadas pasadas, asi que un cedido o un traspasado aparece en otro equipo.
Por eso solo pesa cuando hay varios candidatos igual de parecidos, y en ese caso
se resuelve con el historico de tasaciones: dice por que clubes ha pasado cada
uno, y solo uno habra jugado en el equipo que estamos cargando.

**Los cruces dudosos no se descartan ni se usan.** Se guardan con su puntuacion
y sin revisar, y quedan fuera de la carga hasta que alguien los confirme.
Descartarlos perderia el trabajo; usarlos a ciegas contaminaria los datos con
valores de mercado de otra persona.

**Nunca se inventa un cruce.** Si no hay candidato por encima del umbral, el
jugador se queda sin resolver y el lote sigue.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from futbol_analytics.etl.transfermarkt import parser

logger = logging.getLogger(__name__)

# Por encima de esto el cruce se da por fiable sin revision humana.
CONFIDENT_SCORE = 95.0

# Dos nombres de club se dan por el mismo equipo ("Barcelona" y "FC
# Barcelona") a partir de este parecido.
CLUB_SCORE = 80.0


@dataclass(frozen=True, slots=True)
class Match:
    """Resultado de intentar cruzar a un jugador."""

    understat_id: str
    player_name: str
    transfermarkt_id: str | None
    match_method: str
    match_confidence: float | None
    reviewed: bool

    @property
    def usable(self) -> bool:
        """Si se puede cargar sin revision humana."""
        return self.transfermarkt_id is not None and (self.reviewed or self.is_confident)

    @property
    def is_confident(self) -> bool:
        return (self.match_confidence or 0.0) >= CONFIDENT_SCORE


def normalise(name: str) -> str:
    """Deja un nombre comparable entre fuentes.

    Quita acentos y puntuacion y pasa a minusculas: "Iñaki Peña" y "Inaki Pena"
    son la misma persona, y cada web elige una grafia.

    >>> normalise("Iñaki Peña")
    'inaki pena'
    >>> normalise("A. García-López")
    'a garcia lopez'
    """
    sin_acentos = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    limpio = "".join(c if c.isalnum() else " " for c in sin_acentos.lower())
    return " ".join(limpio.split())


def score(name_a: str, name_b: str) -> float:
    """Parecido entre dos nombres, de 0 a 100.

    Se usa `token_sort_ratio` porque el orden de nombre y apellidos cambia entre
    fuentes: "Pedri Gonzalez" y "Gonzalez Pedri" son el mismo jugador y una
    comparacion literal les daria una puntuacion baja.
    """
    return float(fuzz.token_sort_ratio(normalise(name_a), normalise(name_b)))


def same_club(candidate: dict[str, Any], team: str) -> bool:
    """Si el candidato juega en ese equipo.

    Los nombres de club tampoco coinciden entre fuentes ("Barcelona" frente a
    "FC Barcelona"), asi que se compara con tolerancia y no por igualdad.
    """
    club = (candidate.get("club") or {}).get("name") or ""
    if not club:
        return False
    return score(club, team) >= CLUB_SCORE


# Cuanto puede separarles la puntuacion de nombre y seguir considerandose un
# empate que hay que deshacer por otra via.
TIE_MARGIN = 5.0

# Historiales que se llegan a consultar para deshacer un empate. Cada uno es una
# peticion mas a una fuente ajena, y por encima de esto el empate ya no es un
# homonimo aislado sino un nombre demasiado comun para resolverlo solo.
MAX_HISTORY_LOOKUPS = 4


def tied_candidates(
    player_name: str,
    candidates: list[dict[str, Any]],
    margin: float = TIE_MARGIN,
) -> list[dict[str, Any]]:
    """Candidatos cuyo nombre se parece tanto como el mejor.

    Dos "Robert Lewandowski" al 100 % no se pueden separar por la grafia: hay
    que mirar otra cosa.
    """
    if not candidates:
        return []
    mejor = max(score(player_name, c.get("name", "")) for c in candidates)
    return [c for c in candidates if score(player_name, c.get("name", "")) >= mejor - margin]


def confirm_by_history(
    match: Match,
    team: str,
    candidates: list[dict[str, Any]],
    clubs_of: Callable[[str], list[str]],
) -> Match:
    """Deshace un empate entre homonimos mirando por donde ha pasado cada uno.

    La busqueda solo dice donde juega hoy un futbolista, y eso deja sin resolver
    cruces evidentes: en septiembre de 2026 Transfermarkt situa a Lewandowski en
    el Chicago Fire, asi que al cargar su temporada en el Barcelona no coincidia
    el club, y ademas existe otro Robert Lewandowski retirado con el que empata
    al 100 %.

    La carrera si lo distingue. Si de todos los homonimos solo uno ha jugado en
    ese equipo, es el; y si lo han hecho varios o ninguno, el cruce se queda como
    estaba y espera revision. Se prefiere no resolver a resolver mal: cargar el
    valor de mercado de otra persona es peor que no tener el dato.
    """
    empatados = tied_candidates(match.player_name, candidates)[:MAX_HISTORY_LOOKUPS]
    if len(empatados) < 2:
        return match

    confirmados = [
        c
        for c in empatados
        if any(score(club, team) >= CLUB_SCORE for club in clubs_of(str(c.get("id"))))
    ]
    if len(confirmados) != 1:
        logger.info(
            "El historial no deshace el empate",
            extra={
                "jugador": match.player_name,
                "equipo": team,
                "homonimos": len(empatados),
                "confirmados": len(confirmados),
            },
        )
        return match

    elegido = confirmados[0]
    logger.info(
        "Cruce confirmado por la carrera del jugador",
        extra={"jugador": match.player_name, "equipo": team},
    )
    return Match(
        understat_id=match.understat_id,
        player_name=match.player_name,
        transfermarkt_id=str(elegido.get("id")),
        match_method="history",
        match_confidence=score(match.player_name, elegido.get("name", "")),
        reviewed=False,
    )


def best_match(
    understat_id: str,
    player_name: str,
    team: str,
    candidates: list[dict[str, Any]],
    threshold: float,
) -> Match:
    """Elige el mejor candidato de Transfermarkt para un jugador.

    Se prefiere siempre un candidato del mismo club aunque su nombre se parezca
    menos: el club es un dato mas fiable que la grafia del nombre.
    """
    sin_cruce = Match(understat_id, player_name, None, "fuzzy", None, reviewed=False)
    if not candidates:
        return sin_cruce

    del_club = [c for c in candidates if same_club(c, team)]
    # Si alguno juega en el equipo, los demas ni se miran: es la defensa contra
    # los homonimos.
    considerados = del_club or candidates

    mejor = max(considerados, key=lambda c: score(player_name, c.get("name", "")))
    base = score(player_name, mejor.get("name", ""))

    # El club solo sirve para desempatar, y solo se penaliza su ausencia cuando
    # hay de verdad un empate. Dos razones:
    #
    # 1. Si un unico candidato clava el nombre, no hay homonimo que resolver.
    # 2. La busqueda devuelve el club ACTUAL del jugador, y nosotros cargamos
    #    temporadas pasadas. Un cedido o un traspasado figura en otro equipo, y
    #    penalizarlo por eso marcaba como dudosos cruces evidentes: Lewandowski
    #    y Rashford salian a revision con el nombre acertado al 100 %.
    empatados = tied_candidates(player_name, considerados)
    penalizacion = 15.0 if (not del_club and len(empatados) > 1) else 0.0
    puntuacion = base - penalizacion

    if puntuacion < threshold:
        logger.info(
            "Sin cruce fiable",
            extra={"jugador": player_name, "equipo": team, "mejor": round(puntuacion, 1)},
        )
        return sin_cruce

    return Match(
        understat_id=understat_id,
        player_name=player_name,
        transfermarkt_id=str(mejor.get("id")),
        match_method="exact" if puntuacion >= CONFIDENT_SCORE else "fuzzy",
        match_confidence=round(puntuacion, 2),
        # Un cruce por debajo del umbral de confianza no se usa hasta que
        # alguien lo mire. Se guarda para no repetir la busqueda.
        reviewed=False,
    )


def resolve(
    client: Any,
    understat_id: str,
    player_name: str,
    team: str,
    threshold: float,
) -> Match:
    """Busca en Transfermarkt y devuelve el mejor cruce.

    Si el cruce se queda por debajo de la confianza por un empate entre
    homonimos, se intenta deshacer con el historico de cada uno antes de
    mandarlo a revision manual.
    """
    candidatos = client.search_player(player_name)
    cruce = best_match(understat_id, player_name, team, candidatos, threshold)
    if cruce.transfermarkt_id is None or cruce.is_confident:
        return cruce

    def clubes_de(transfermarkt_id: str) -> list[str]:
        try:
            return parser.clubs_in_history(client.market_value(transfermarkt_id))
        except Exception as error:  # noqa: BLE001
            # Un historial que no se puede leer solo significa que ese candidato
            # no queda confirmado; no debe tumbar la resolucion del jugador.
            logger.warning(
                "No se pudo leer el historial de un candidato",
                extra={"transfermarkt_id": transfermarkt_id, "motivo": str(error)},
            )
            return []

    return confirm_by_history(cruce, team, candidatos, clubes_de)
