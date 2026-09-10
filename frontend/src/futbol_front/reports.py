"""Informe de jugador en PDF, de una página.

Convierte la plataforma en algo que un ojeador se lleva a una reunión. Es la
diferencia entre un panel que hay que abrir con un portátil delante y un
documento que se imprime, se anota a mano y se pasa por encima de la mesa.

**Se genera con matplotlib y no con una librería de PDF.** El documento propuso
`reportlab` o `weasyprint`; ninguna hace falta. Todos los gráficos ya se dibujan
con matplotlib, que exporta PDF vectorial de serie, y `PyPizza` acepta pintar en
un eje que se le pasa, así que el radar entra en la página sin convertirse en
imagen. `weasyprint` además arrastra librerías del sistema (cairo, pango) que
engordarían una imagen que hoy es ligera, y el proyecto tiene por norma no
añadir peso sin necesidad.

**Una página, no varias.** Un informe de scouting que ocupa tres hojas no se
lee: se archiva. Lo que cabe en una es lo que de verdad hace falta para decidir
si un jugador merece una segunda mirada, y esta plataforma tiene una opinión
clara sobre qué es eso: el perfil, su lectura, el contexto de mercado y las
advertencias que evitan leerlo mal.

**Las advertencias van en el informe, no se quedan en la pantalla.** Es donde
más importan: el PDF circula solo, sin nadie que explique que el percentil se
calculó sobre cinco jornadas.
"""

from __future__ import annotations

import io
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from mplsoccer import PyPizza

from futbol_front import charts, presentation
from futbol_front.presentation import PizzaData, season_label
from futbol_front.theme import DEFAULT, Palette

# A4 en pulgadas. Se imprime, así que el tamaño es el del papel y no el de la
# pantalla.
A4 = (8.27, 11.69)

# Fondo claro: un informe se imprime, y el tema oscuro de la interfaz gastaría
# un cartucho por hoja además de leerse peor en papel.
PAPER = "#FFFFFF"
INK = "#14181F"
MUTED = "#5B6577"
RULE = "#D8DCE4"

# Comparables que caben sin apretar el pie de página.
MAX_COMPARABLES = 5

# Métricas de la tabla. Más no caben legibles, y las de la plantilla del gráfico
# son justo las que el radar ya está enseñando.
MAX_METRICAS = 10


def player_report(
    profile: dict[str, Any],
    template: list[dict[str, Any]],
    market: dict[str, Any] | None = None,
    similar: dict[str, Any] | None = None,
    palette: Palette = DEFAULT,
) -> bytes:
    """Genera el informe de un jugador y lo devuelve como PDF."""
    ficha = profile["player"]
    figura = plt.figure(figsize=A4)
    figura.patch.set_facecolor(PAPER)

    _cabecera(figura, ficha, profile, palette)
    _radar(figura, profile, template, palette)
    _contexto(figura, market, palette)
    _lectura(figura, profile)
    _tabla(figura, profile, template)
    _comparables(figura, similar, palette)
    _pie(figura, profile)

    buffer = io.BytesIO()
    figura.savefig(buffer, format="pdf", facecolor=PAPER, bbox_inches=None)
    plt.close(figura)
    return buffer.getvalue()


def _cabecera(figura: Figure, ficha: dict, profile: dict, palette: Palette) -> None:
    figura.text(0.06, 0.955, ficha["player"], size=22, weight="bold", color=INK)

    rol = ficha.get("detailed_position") or ficha.get("position_group") or "sin posición"
    figura.text(
        0.06,
        0.933,
        f"{ficha['team']} · {ficha['league']} · {season_label(ficha['season'])} · {rol}",
        size=9.5,
        color=MUTED,
    )
    figura.text(0.94, 0.955, charts.BRAND, size=11, weight="bold", ha="right", color=palette.accent)
    figura.text(
        0.94,
        0.936,
        f"Percentil frente a {profile['population_size']} jugadores de las Big 5",
        size=7.5,
        ha="right",
        color=MUTED,
    )
    _regla(figura, 0.925)


def _radar(figura: Figure, profile: dict, template: list[dict], palette: Palette) -> None:
    """El pizza chart, dibujado dentro de la página y no pegado como imagen.

    `PyPizza` acepta el eje de destino, así que el radar sale vectorial y se
    puede ampliar en el PDF sin pixelarse.
    """
    datos = presentation.prepare_pizza(profile, template)
    ejes = figura.add_axes((0.04, 0.545, 0.50, 0.36), polar=True)

    if not len(datos):
        ejes.set_axis_off()
        figura.text(0.29, 0.72, "Sin percentiles calculables", size=9, ha="center", color=MUTED)
        return

    colores = [charts.CATEGORY_COLORS.get(c, charts.UNKNOWN_CATEGORY) for c in datos.categories]
    baker = PyPizza(
        params=datos.labels,
        background_color=PAPER,
        straight_line_color=RULE,
        straight_line_lw=1,
        last_circle_color=RULE,
        last_circle_lw=1.2,
        other_circle_lw=0,
        inner_circle_size=14,
    )
    baker.make_pizza(
        datos.values,
        ax=ejes,
        color_blank_space="same",
        slice_colors=colores,
        value_colors=["#FFFFFF"] * len(datos),
        value_bck_colors=colores,
        blank_alpha=0.25,
        kwargs_slices={"edgecolor": PAPER, "zorder": 2, "linewidth": 1},
        kwargs_params={"color": INK, "fontsize": 7.5, "va": "center"},
        kwargs_values={
            "color": "#FFFFFF",
            "fontsize": 7,
            "zorder": 3,
            "bbox": {"edgecolor": PAPER, "boxstyle": "round,pad=0.15", "lw": 1},
        },
    )

    for x, categoria in zip((0.12, 0.28, 0.44), charts.CATEGORY_COLORS, strict=False):
        figura.text(
            x,
            0.525,
            categoria,
            size=7.5,
            color=charts.CATEGORY_COLORS[categoria],
            weight="bold",
        )
    _sin_datos(figura, datos)


def _sin_datos(figura: Figure, datos: PizzaData) -> None:
    if datos.missing:
        figura.text(
            0.04,
            0.508,
            "Sin datos para: " + ", ".join(datos.missing),
            size=6.5,
            color=MUTED,
        )


def _contexto(figura: Figure, market: dict | None, palette: Palette) -> None:
    """Edad, contrato y valor: lo que un percentil por sí solo no dice."""
    figura.text(0.58, 0.895, "CONTEXTO", size=8, weight="bold", color=palette.accent)

    if not market or not market.get("card"):
        figura.text(
            0.58,
            0.872,
            "Sin ficha de Transfermarkt para este jugador.",
            size=8,
            color=MUTED,
        )
        return

    tarjeta = market["card"]
    valor = market.get("current_value_eur")
    filas = [
        ("Edad", tarjeta.get("age") or "-"),
        ("Posición", tarjeta.get("position") or "-"),
        ("Pie", (tarjeta.get("foot") or "-").capitalize()),
        ("Contrato hasta", tarjeta.get("contract_until") or "-"),
        ("Valor de mercado", f"{valor / 1e6:.1f} M €" if valor else "-"),
        ("Máximo histórico", _millones(market.get("peak_value_eur"))),
    ]
    for i, (etiqueta, dato) in enumerate(filas):
        y = 0.872 - i * 0.021
        figura.text(0.58, y, etiqueta, size=7.5, color=MUTED)
        figura.text(0.94, y, str(dato), size=8, ha="right", weight="bold", color=INK)


def _lectura(figura: Figure, profile: dict) -> None:
    """El resumen y dónde se sale de lo normal, con sus matices."""
    figura.text(0.58, 0.720, "LECTURA", size=8, weight="bold", color=MUTED)
    figura.text(
        0.58,
        0.698,
        _envolver(presentation.summarise_profile(profile), 44),
        size=8.5,
        va="top",
        color=INK,
    )

    avisos = presentation.extreme_metrics(profile)[:4]
    y = 0.648
    for aviso in avisos:
        marca = {"fortaleza": "▲", "debilidad": "▼", "rasgo": "●"}[aviso.kind]
        figura.text(0.58, y, f"{marca}  {aviso.text}", size=7.5, color=INK)
        y -= 0.019
        if aviso.note:
            figura.text(0.60, y, _envolver(f"Ojo: {aviso.note}", 52), size=6, color=MUTED)
            y -= 0.024


def _tabla(figura: Figure, profile: dict, template: list[dict]) -> None:
    """El detalle numérico, para quien quiera el valor y no el percentil."""
    _regla(figura, 0.492)
    figura.text(0.06, 0.472, "DETALLE NUMÉRICO", size=8, weight="bold", color=MUTED)

    del_grafico = [s["metric"] for s in template]
    metricas = [
        m
        for m in profile["metrics"]
        if m["metric"] in del_grafico and m.get("percentile") is not None
    ][:MAX_METRICAS]

    cabeceras = (("Métrica", 0.06), ("Total", 0.30), ("Por 90", 0.38), ("Percentil", 0.47))
    for texto, x in cabeceras:
        figura.text(x, 0.452, texto, size=7, weight="bold", color=MUTED)

    for i, metrica in enumerate(metricas):
        y = 0.436 - i * 0.0175
        figura.text(0.06, y, metrica["label"], size=7.5, color=INK)
        figura.text(0.30, y, _numero(metrica.get("total")), size=7.5, color=INK)
        figura.text(0.38, y, _numero(metrica.get("per90"), 2), size=7.5, color=INK)
        figura.text(0.47, y, f"{metrica['percentile']:.0f}", size=7.5, weight="bold", color=INK)


def _comparables(figura: Figure, similar: dict | None, palette: Palette) -> None:
    """Quién más juega así, que es la pregunta con la que sigue un ojeador."""
    figura.text(0.58, 0.472, "PERFILES PARECIDOS", size=8, weight="bold", color=palette.accent)

    vecinos = (similar or {}).get("neighbours", [])[:MAX_COMPARABLES]
    if not vecinos:
        figura.text(0.58, 0.450, "Sin comparables calculables.", size=7.5, color=MUTED)
        return

    for i, vecino in enumerate(vecinos):
        y = 0.450 - i * 0.030
        figura.text(0.58, y, f"{vecino['player']} · {vecino['team']}", size=7.5, color=INK)
        figura.text(
            0.94,
            y,
            f"{vecino['similarity']:.0f} %",
            size=7.5,
            ha="right",
            weight="bold",
            color=palette.accent,
        )
        figura.text(
            0.60,
            y - 0.013,
            f"Coinciden en {', '.join(vecino['closest']).lower()}",
            size=6,
            color=MUTED,
        )


def _pie(figura: Figure, profile: dict) -> None:
    """Advertencias y firma.

    Las advertencias van en el informe y no se quedan en la pantalla porque es
    donde más importan: el PDF circula solo, sin nadie que explique que el
    percentil se calculó sobre cinco jornadas.
    """
    _regla(figura, 0.255)
    figura.text(0.06, 0.235, "CÓMO LEER ESTO", size=8, weight="bold", color=MUTED)

    avisos = list(profile.get("caveats", []))
    avisos.append(
        "El percentil dice dónde está un jugador respecto a sus comparables, no cuánto "
        "hace. Las métricas sin dirección describen cómo juega, no lo bueno que es."
    )

    y = 0.213
    for aviso in avisos[:4]:
        figura.text(0.06, y, _envolver(f"· {aviso}", 118), size=6.8, va="top", color=MUTED)
        y -= 0.022 * (1 + len(aviso) // 118)

    figura.text(0.06, 0.035, charts.BRAND, size=7.5, weight="bold", color=MUTED)
    figura.text(0.94, 0.035, charts.DATA_SOURCE, size=7, ha="right", color=MUTED)


def _regla(figura: Figure, y: float) -> None:
    figura.add_artist(
        plt.Line2D((0.06, 0.94), (y, y), color=RULE, linewidth=0.8, transform=figura.transFigure)
    )


def _envolver(texto: str, ancho: int) -> str:
    """Parte el texto a mano: matplotlib no ajusta líneas por sí solo."""
    palabras, lineas, actual = texto.split(), [], ""
    for palabra in palabras:
        if len(actual) + len(palabra) + 1 > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return "\n".join(lineas)


def _numero(valor: object, decimales: int = 0) -> str:
    if valor is None:
        return "-"
    return f"{float(valor):.{decimales}f}"


def _millones(valor: float | None) -> str:
    return "-" if valor is None else f"{valor / 1e6:.1f} M €"
