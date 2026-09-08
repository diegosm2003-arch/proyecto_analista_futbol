"""Graficos. Capa fina sobre `presentation`, que es quien decide los datos.

El pizza chart usa `mplsoccer`, que es la libreria estandar en football
analytics y produce el mismo lenguaje visual que los graficos de FBref: quien
los conozca no tiene que aprender a leerlos.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from mplsoccer import PyPizza

from futbol_analytics.app.presentation import PizzaData, StyleMapData
from futbol_analytics.templates import ATTACK, DEFENCE, POSSESSION

# Un color por categoria. Se distinguen bien en pantalla y tambien impresos en
# gris, que importa si el grafico acaba en un post o en una presentacion.
CATEGORY_COLORS = {
    ATTACK: "#D9455F",
    POSSESSION: "#3C7DC4",
    DEFENCE: "#4F9D69",
}

BACKGROUND = "#F5F5F0"
TEXT = "#1B1B1B"
GRID = "#D8D8D2"


def pizza(data: PizzaData, title: str, subtitle: str) -> Figure:
    """Dibuja el pizza chart de un jugador.

    Cada porcion es un percentil dentro de su poblacion, no un valor absoluto:
    la longitud dice donde esta respecto a sus comparables, no cuanto hace.
    """
    if not len(data):
        raise ValueError("No hay metricas con percentil para dibujar el grafico.")

    colores = [CATEGORY_COLORS.get(categoria, "#8A8A8A") for categoria in data.categories]

    baker = PyPizza(
        params=data.labels,
        background_color=BACKGROUND,
        straight_line_color=GRID,
        straight_line_lw=1,
        last_circle_color=GRID,
        last_circle_lw=1.5,
        other_circle_lw=0,
        inner_circle_size=18,
    )

    figura, ejes = baker.make_pizza(
        data.values,
        figsize=(8.0, 8.6),
        color_blank_space="same",
        slice_colors=colores,
        value_colors=["#FFFFFF"] * len(data),
        value_bck_colors=colores,
        blank_alpha=0.35,
        kwargs_slices={"edgecolor": BACKGROUND, "zorder": 2, "linewidth": 1},
        kwargs_params={"color": TEXT, "fontsize": 10, "va": "center"},
        kwargs_values={
            "color": "#FFFFFF",
            "fontsize": 10,
            "zorder": 3,
            "bbox": {"edgecolor": "#000000", "boxstyle": "round,pad=0.2", "lw": 1},
        },
    )

    figura.text(0.515, 0.975, title, size=16, ha="center", color=TEXT, weight="bold")
    figura.text(0.515, 0.947, subtitle, size=10, ha="center", color="#5A5A5A")
    _legend(figura)
    ejes.set_facecolor(BACKGROUND)
    return figura


def _legend(figura: Figure) -> None:
    """Leyenda de categorias, en el pie del grafico."""
    posiciones = {ATTACK: 0.30, POSSESSION: 0.50, DEFENCE: 0.70}
    for categoria, x in posiciones.items():
        figura.text(
            x,
            0.022,
            categoria,
            size=11,
            ha="center",
            color=CATEGORY_COLORS[categoria],
            weight="bold",
        )


def style_map(data: StyleMapData, title: str) -> Figure:
    """Mapa de estilos: posesion frente a altura de presion.

    El eje vertical se invierte porque una PPDA baja significa presion alta:
    dejarlo sin invertir situaria a los equipos mas agresivos abajo, que es lo
    contrario de lo que la vista sugiere intuitivamente.
    """
    if not len(data):
        raise ValueError("No hay equipos con posesion y presion conocidas.")

    figura, ejes = plt.subplots(figsize=(9.0, 6.5))
    figura.patch.set_facecolor(BACKGROUND)
    ejes.set_facecolor(BACKGROUND)

    colores = plt.get_cmap("tab10")
    for cluster in sorted(set(data.clusters)):
        indices = [i for i, valor in enumerate(data.clusters) if valor == cluster]
        etiqueta = data.styles[indices[0]]
        ejes.scatter(
            [data.possession[i] for i in indices],
            [data.ppda[i] for i in indices],
            s=110,
            color=colores(cluster % 10),
            edgecolor=BACKGROUND,
            linewidth=1.2,
            label=etiqueta,
            zorder=3,
        )

    for i, equipo in enumerate(data.teams):
        ejes.annotate(
            equipo,
            (data.possession[i], data.ppda[i]),
            xytext=(6, 4),
            textcoords="offset points",
            fontsize=8,
            color=TEXT,
        )

    ejes.invert_yaxis()
    ejes.set_xlabel("Posesion (%)", color=TEXT)
    ejes.set_ylabel("PPDA aproximada (arriba = mas presion)", color=TEXT)
    ejes.set_title(title, color=TEXT, weight="bold", fontsize=14)
    ejes.grid(color=GRID, linewidth=0.8, zorder=1)
    ejes.legend(loc="best", fontsize=8, frameon=True, facecolor=BACKGROUND)
    figura.tight_layout()
    return figura
