"""Plantillas de metricas para el pizza chart.

Que se pinta en el grafico de un jugador es una decision futbolistica, no de
interfaz. Por eso vive aqui, junto al catalogo de metricas, y se expone por la
API: la interfaz y el chat usan exactamente los mismos ejes.

**Ocho ejes fijos, no un desplegable.** Un selector con todas las metricas
convierte cada grafico en uno distinto e impide comparar dos jugadores de un
vistazo, que es justo para lo que sirve un pizza chart.

**Tres categorias: finalizacion, creacion y construccion.** No son las de FBref
(ataque / posesion / defensa) porque Understat no publica acciones defensivas.
Estas tres describen lo que si medimos, y separan tres formas de aportar al
ataque que suelen confundirse: rematar, dar el ultimo pase, y participar en la
jugada sin hacer ninguna de las dos cosas.
"""

from __future__ import annotations

from dataclasses import dataclass

# Categorias en el orden en que se recorren las porciones del grafico.
#
# No son las de FBref (ataque / posesion / defensa) porque no medimos defensa:
# Understat no publica acciones defensivas. Estas tres si describen lo que hay,
# y ademas separan tres formas distintas de aportar al ataque que a menudo se
# confunden en una sola cifra de goles y asistencias.
FINISHING = "Finalización"
CREATION = "Creación"
BUILDUP = "Construcción"
CATEGORIES: tuple[str, ...] = (FINISHING, CREATION, BUILDUP)


@dataclass(frozen=True, slots=True)
class Slice:
    """Una porcion del grafico: una metrica dentro de una categoria."""

    metric: str
    category: str


def _slices(por_categoria: dict[str, tuple[str, ...]]) -> tuple[Slice, ...]:
    """Construye las porciones respetando el orden de las categorias.

    Recibe un diccionario y no argumentos con nombre porque las categorias
    llevan tilde —son texto que ve el usuario— y una tilde no cabe en el nombre
    de un parametro de Python.
    """
    return tuple(
        Slice(metric=metrica, category=categoria)
        for categoria in CATEGORIES
        for metrica in por_categoria.get(categoria, ())
    )


# Una sola plantilla para los jugadores de campo. Con el catalogo de Understat
# no tiene sentido cambiar los ejes por posicion: las metricas disponibles son
# las mismas para un central y para un delantero, y lo que los distingue es el
# PERFIL que dibujan, no que se midan cosas distintas. Un central aparecera
# fuerte en construccion y flojo en finalizacion, que es exactamente lo que
# queremos que se vea de un vistazo.
OUTFIELD_TEMPLATE: tuple[Slice, ...] = _slices(
    {
        FINISHING: ("np_goals", "np_xg", "shots"),
        CREATION: ("assists", "xa", "key_passes"),
        BUILDUP: ("xg_chain", "xg_buildup"),
    }
)

PIZZA_TEMPLATES: dict[str, tuple[Slice, ...]] = {
    "DF": OUTFIELD_TEMPLATE,
    "MF": OUTFIELD_TEMPLATE,
    "FW": OUTFIELD_TEMPLATE,
}

# Los porteros no tienen plantilla: Understat no publica ninguna metrica de
# porteria. Es una limitacion del dato, no una decision de diseno.
NO_TEMPLATE = ("GK",)


def template_for(position_group: str | None) -> tuple[Slice, ...]:
    """Plantilla de una posicion. Vacia si no tiene grafico definido."""
    if position_group is None or position_group in NO_TEMPLATE:
        return ()
    return PIZZA_TEMPLATES.get(position_group, ())
