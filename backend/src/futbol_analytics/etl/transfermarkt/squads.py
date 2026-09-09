"""Cruce de identidades a traves de la plantilla del club.

Es la forma buena de cruzar las dos fuentes, y sustituye a buscar cada nombre en
todo Transfermarkt.

El razonamiento es futbolistico antes que tecnico. Buscar "Toni Fernandez" en
una base con medio millon de fichas devuelve homonimos de medio mundo, y hay que
adivinar cual es. Pero un jugador del Barcelona esta, por definicion, en la
plantilla del Barcelona: comparar su nombre contra los veintitantos companeros
que Transfermarkt le atribuye a ese club convierte un problema de identificacion
global en uno local, donde dos nombres casi iguales practicamente no existen.

Ademas sale mucho mas barato. Una liga entera son 1 peticion para los clubes mas
1 por club: veintiuna en total, frente a las mas de cuatrocientas busquedas que
hacia falta antes.

Y de propina trae la ficha de cada jugador (fecha de nacimiento, posicion
concreta, pie, contrato) sin una sola peticion extra, que es el contexto que a un
percentil por si solo le falta: un percentil 95 no significa lo mismo a los 19
anos que a los 33.
"""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz

from futbol_analytics.etl.transfermarkt.matching import (
    CONFIDENT_SCORE,
    Match,
    normalise,
    score,
    tied_candidates,
)

logger = logging.getLogger(__name__)

# Identificador de cada liga en Transfermarkt. Se escribe a mano porque son
# cinco y no cambian; buscarlas por nombre anadiria un punto de fallo para
# resolver algo que ya sabemos.
COMPETITION_IDS = {
    "ESP-La Liga": "ES1",
    "ENG-Premier League": "GB1",
    "ITA-Serie A": "IT1",
    "GER-Bundesliga": "L1",
    "FRA-Ligue 1": "FR1",
}

# Parecido minimo para dar por bueno que dos nombres de club son el mismo
# equipo.
CLUB_NAME_SCORE = 70.0


def club_score(team: str, club_name: str) -> tuple[float, float]:
    """Parecido entre el nombre de un equipo nuestro y uno de Transfermarkt.

    Devuelve dos numeros porque hace falta mirar dos cosas, y ninguna de las dos
    basta sola.

    El primero ignora las palabras que sobran: Understat escribe "Alaves" y
    "Espanyol" donde Transfermarkt pone "Deportivo Alaves" y "RCD Espanyol
    Barcelona". Comparando palabra a palabra, esos nombres se parecen poco
    —cincuenta y pico sobre cien— y el equipo se quedaba sin plantilla.

    El segundo desempata, y evita el desastre que provoca el primero por su
    cuenta: "Barcelona" esta contenido tanto en "FC Barcelona" como en "RCD
    Espanyol Barcelona", asi que los dos puntuan 100 y el Barcelona podia
    acabar con la plantilla del Espanyol. Un error de cruce afecta a un jugador;
    uno de club, a un equipo entero. Penalizando las palabras de mas, "FC
    Barcelona" saca 86 y "RCD Espanyol Barcelona" se queda en 53.
    """
    a, b = normalise(team), normalise(club_name)
    return float(fuzz.token_set_ratio(a, b)), float(fuzz.token_sort_ratio(a, b))


def match_club(team: str, clubs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Encuentra el club de Transfermarkt que corresponde a un equipo nuestro.

    Solo se comparan los clubes de esa competicion, asi que no hay forma de
    confundir el Barcelona con el Barcelona SC de Ecuador. Dentro de la liga, un
    empate en los dos criterios se deja sin resolver: dar por bueno el primero
    de la lista significaria cargar una plantilla entera equivocada.
    """
    if not clubs:
        return None

    ordenados = sorted(clubs, key=lambda c: club_score(team, c.get("name", "")), reverse=True)
    mejor = ordenados[0]
    puntuacion = club_score(team, mejor.get("name", ""))

    if puntuacion[0] < CLUB_NAME_SCORE:
        logger.warning(
            "Equipo sin club en Transfermarkt",
            extra={"equipo": team, "mejor": mejor.get("name"), "parecido": round(puntuacion[0], 1)},
        )
        return None

    if len(ordenados) > 1 and club_score(team, ordenados[1].get("name", "")) == puntuacion:
        logger.warning(
            "Dos clubes empatan para el mismo equipo",
            extra={"equipo": team, "candidatos": [mejor.get("name"), ordenados[1].get("name")]},
        )
        return None

    return mejor


def match_in_squad(
    understat_id: str,
    player_name: str,
    squad: list[dict[str, Any]],
    threshold: float,
) -> Match:
    """Cruza a un jugador contra la plantilla de su club.

    Un cruce dentro de la plantilla se da por fiable aunque el nombre no sea
    identico: la coincidencia de club ya es una prueba fortisima de identidad, y
    exigir ademas un parecido de nombre casi perfecto solo dejaria fuera
    grafias distintas de la misma persona ("Alex Balde" y "Alejandro Balde").

    La excepcion son los companeros de equipo que se llaman casi igual: ahi el
    club no desempata porque los dos estan en el mismo, y decide una persona.
    """
    sin_cruce = Match(understat_id, player_name, None, "squad", None, reviewed=False)
    if not squad:
        return sin_cruce

    mejor = max(squad, key=lambda j: score(player_name, j.get("name", "")))
    puntuacion = score(player_name, mejor.get("name", ""))
    if puntuacion < threshold:
        logger.info(
            "Sin cruce en la plantilla",
            extra={"jugador": player_name, "mejor": round(puntuacion, 1)},
        )
        return sin_cruce

    # Dos companeros con nombres casi iguales: el club no distingue.
    empatados = tied_candidates(player_name, squad)
    if len(empatados) > 1:
        logger.info(
            "Dos companeros con nombres casi iguales",
            extra={"jugador": player_name, "candidatos": len(empatados)},
        )
        return Match(
            understat_id=understat_id,
            player_name=player_name,
            transfermarkt_id=str(mejor.get("id")),
            match_method="squad",
            match_confidence=round(min(puntuacion, CONFIDENT_SCORE - 1), 2),
            reviewed=False,
        )

    return Match(
        understat_id=understat_id,
        player_name=player_name,
        transfermarkt_id=str(mejor.get("id")),
        match_method="squad",
        # Estar en la plantilla es la prueba, no el parecido del nombre.
        match_confidence=CONFIDENT_SCORE,
        reviewed=False,
    )
