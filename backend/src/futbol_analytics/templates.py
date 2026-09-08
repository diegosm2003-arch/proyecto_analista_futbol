"""Plantillas de metricas para el pizza chart.

Que se pinta en el grafico de un jugador es una decision futbolistica, no de
interfaz. Por eso vive aqui, junto al catalogo de metricas, y se expone por la
API: la interfaz y el chat usan exactamente los mismos ejes.

**Doce ejes fijos por posicion, no un desplegable.** Un selector con las 45
metricas convierte cada grafico en uno distinto e impide comparar dos jugadores
de un vistazo, que es justo para lo que sirve un pizza chart. Doce es el limite
practico de legibilidad: por encima, las porciones son demasiado estrechas para
leer la etiqueta.

**Tres categorias: ataque, posesion y defensa.** Es la agrupacion de FBref, ya
conocida por quien lee este tipo de graficos, y hace evidente de un golpe de
vista si un jugador aporta arriba, en la circulacion o atras.

Las metricas se eligen por posicion, no por rol: un lateral y un central
comparten plantilla aunque tengan roles distintos. Es deliberado, porque cambiar
los ejes segun el rol haria incomparables dos defensas, y el rol ya se muestra
como etiqueta junto al grafico.
"""

from __future__ import annotations

from dataclasses import dataclass

# Categorias en el orden en que se recorren las porciones del grafico.
ATTACK = "Ataque"
POSSESSION = "Posesion"
DEFENCE = "Defensa"
CATEGORIES: tuple[str, ...] = (ATTACK, POSSESSION, DEFENCE)


@dataclass(frozen=True, slots=True)
class Slice:
    """Una porcion del grafico: una metrica dentro de una categoria."""

    metric: str
    category: str


def _slices(**por_categoria: tuple[str, ...]) -> tuple[Slice, ...]:
    """Construye las porciones respetando el orden de las categorias."""
    return tuple(
        Slice(metric=metrica, category=categoria)
        for categoria in CATEGORIES
        for metrica in por_categoria.get(categoria, ())
    )


PIZZA_TEMPLATES: dict[str, tuple[Slice, ...]] = {
    # Defensas. El peso esta en la salida de balon y en el duelo, que es lo que
    # separa a un central de construccion de uno de area. Se incluyen los
    # centros al area porque son el rasgo que delata al lateral dentro del grupo.
    "DF": _slices(
        Ataque=("npxg", "xag", "touches_att_pen"),
        Posesion=(
            "passes_completed",
            "progressive_passes",
            "passes_into_final_third",
            "progressive_carries",
            "crosses_into_penalty_area",
        ),
        Defensa=("tackles", "interceptions", "clearances", "aerials_won"),
    ),
    # Centrocampistas. Reparto equilibrado: un mediocentro se juzga por lo que
    # aporta en las tres fases, y el perfil del grafico es lo que distingue al
    # pivote del mediapunta.
    "MF": _slices(
        Ataque=("npxg", "xag", "shots", "touches_att_pen"),
        Posesion=(
            "progressive_passes",
            "passes_into_final_third",
            "key_passes",
            "progressive_carries",
        ),
        Defensa=("tackles", "interceptions", "ball_recoveries", "dribblers_tackled"),
    ),
    # Delanteros. Se muestran goles y npxG juntos a proposito: la distancia entre
    # ambos es la historia (si finaliza por encima o por debajo de lo esperado),
    # y ese contraste se pierde si solo se ensena uno.
    "FW": _slices(
        Ataque=("npxg", "goals", "shots", "touches_att_pen", "xag"),
        Posesion=(
            "progressive_passes_received",
            "take_ons_successful",
            "carries_into_penalty_area",
            "key_passes",
        ),
        Defensa=("tackles", "ball_recoveries", "aerials_won"),
    ),
}

# Los porteros no tienen plantilla. Del catalogo publico de FBref solo se cargan
# tres metricas de porteria (goles encajados, paradas y PSxG), y un pizza chart
# de tres porciones no dice nada que no diga mejor una tabla. Es una limitacion
# del dato disponible, no una decision de diseno: se resolveria anadiendo las
# tablas avanzadas de portero al ETL.
NO_TEMPLATE = ("GK",)


def template_for(position_group: str | None) -> tuple[Slice, ...]:
    """Plantilla de una posicion. Vacia si no tiene grafico definido."""
    if position_group is None or position_group in NO_TEMPLATE:
        return ()
    return PIZZA_TEMPLATES.get(position_group, ())
