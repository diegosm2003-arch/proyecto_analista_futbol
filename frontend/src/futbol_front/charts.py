"""Graficos. Capa fina sobre `presentation`, que es quien decide los datos.

El pizza chart usa `mplsoccer`, que es la libreria estandar en football
analytics y produce el mismo lenguaje visual que los graficos de FBref: quien
los conozca no tiene que aprender a leerlos.

**Todos los graficos aceptan la paleta de la liga.** El fondo es oscuro y el
acento cambia con la competicion, para que el grafico no desentone con la
pantalla en la que vive. Las categorias mantienen su color en todas las ligas:
son la clave de lectura del grafico y cambiarlas obligaria a releer la leyenda
cada vez.

**Los tamanos son deliberadamente contenidos.** Un pizza chart a pantalla
completa obliga a bajar para ver la tabla y los jugadores parecidos, y en una
herramienta de scouting lo que importa es tener el perfil, el contexto y los
comparables a la vez.
"""

from __future__ import annotations

import io

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from mplsoccer import PyPizza, VerticalPitch

from futbol_front.presentation import ComparisonData, PizzaData, StyleMapData
from futbol_front.theme import DEFAULT, Palette

# Categorias tal y como las sirve la API en /meta/templates. Se repiten aqui en
# lugar de importarlas del backend: la taxonomia es suya, la paleta es de la
# interfaz. Si el backend anadiera una categoria nueva, sus porciones saldrian
# en gris en lugar de romper el grafico.
#
# No son ataque / posesion / defensa como en FBref porque no medimos defensa.
# Estas tres separan tres formas distintas de aportar al ataque que una cifra
# de goles y asistencias confunde en una sola.
FINISHING, CREATION, BUILDUP = "Finalización", "Creación", "Construcción"

# Paleta de Okabe-Ito, disenada para distinguirse con cualquier tipo de
# daltonismo. Sustituye a una eleccion "a ojo" que mezclaba rojo y verde, que es
# justo el par que una de cada doce personas no separa.
#
# El color nunca es el unico canal: las porciones del pizza llevan ademas su
# etiqueta, y los grupos del mapa de estilos, su marcador.
OKABE_ITO = (
    "#E69F00",  # naranja
    "#56B4E9",  # azul cielo
    "#009E73",  # verde azulado
    "#F0E442",  # amarillo
    "#0072B2",  # azul
    "#D55E00",  # bermellon
    "#CC79A7",  # rosa
    "#999999",  # gris
)

# Un color por categoria, constante entre ligas. Se distinguen bien en pantalla
# y tambien impresos en gris, que importa si el grafico acaba en un post.
CATEGORY_COLORS = {
    FINISHING: OKABE_ITO[5],
    CREATION: OKABE_ITO[1],
    BUILDUP: OKABE_ITO[2],
}
UNKNOWN_CATEGORY = OKABE_ITO[7]

# Marcadores para los grupos del mapa de estilos. Con doce o dieciseis grupos no
# hay paleta que aguante, asi que la forma hace de segundo canal.
CLUSTER_MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")

# Fondo y tinta de los graficos. Coinciden con el tema oscuro de la interfaz.
BACKGROUND = "#161D2B"
TEXT = "#E9EDF5"
TEXT_MUTED = "#8D9AB4"
GRID = "#2A344A"

# Tamanos. El pizza cabe junto a su panel de detalle sin obligar a bajar.
PIZZA_SIZE = (5.4, 5.8)
COMPARE_SIZE = (6.0, 6.4)
MAP_SIZE = (7.2, 5.6)
SMALL_SIZE = (5.2, 3.2)


def pizza(data: PizzaData, title: str, subtitle: str, palette: Palette = DEFAULT) -> Figure:
    """Dibuja el pizza chart de un jugador.

    Cada porcion es un percentil dentro de su poblacion, no un valor absoluto:
    la longitud dice donde esta respecto a sus comparables, no cuanto hace.
    """
    if not len(data):
        raise ValueError("No hay métricas con percentil para dibujar el gráfico.")

    colores = [CATEGORY_COLORS.get(categoria, UNKNOWN_CATEGORY) for categoria in data.categories]

    baker = PyPizza(
        params=data.labels,
        background_color=BACKGROUND,
        straight_line_color=GRID,
        straight_line_lw=1,
        last_circle_color=GRID,
        last_circle_lw=1.5,
        other_circle_lw=0,
        inner_circle_size=16,
    )

    figura, ejes = baker.make_pizza(
        data.values,
        figsize=PIZZA_SIZE,
        color_blank_space="same",
        slice_colors=colores,
        value_colors=["#0E1420"] * len(data),
        value_bck_colors=colores,
        blank_alpha=0.28,
        kwargs_slices={"edgecolor": BACKGROUND, "zorder": 2, "linewidth": 1},
        kwargs_params={"color": TEXT, "fontsize": 8, "va": "center"},
        kwargs_values={
            "color": "#0E1420",
            "fontsize": 8,
            "zorder": 3,
            "bbox": {"edgecolor": BACKGROUND, "boxstyle": "round,pad=0.15", "lw": 1},
        },
    )

    figura.text(0.515, 0.985, title, size=13, ha="center", color=TEXT, weight="bold")
    figura.text(0.515, 0.955, subtitle, size=8, ha="center", color=palette.accent)
    _legend(figura)
    ejes.set_facecolor(BACKGROUND)
    return figura


def _legend(figura: Figure) -> None:
    """Leyenda de categorias, en el pie del grafico."""
    posiciones = {FINISHING: 0.24, CREATION: 0.50, BUILDUP: 0.76}
    for categoria, x in posiciones.items():
        figura.text(
            x,
            0.015,
            categoria,
            size=8,
            ha="center",
            color=CATEGORY_COLORS[categoria],
            weight="bold",
        )


def similarity_bars(
    names: list[str],
    scores: list[float],
    palette: Palette = DEFAULT,
) -> Figure:
    """Barras horizontales con el parecido de cada jugador comparable.

    Horizontales porque lo que hay que leer son nombres, y un nombre en
    vertical no se lee. El eje arranca en el minimo de la serie y no en cero a
    proposito: todos los vecinos rondan porcentajes altos, asi que un eje desde
    cero los dejaria practicamente iguales y no ensenaria nada.
    """
    if not names:
        raise ValueError("No hay jugadores parecidos que dibujar.")

    figura, ejes = _lienzo(SMALL_SIZE)
    posiciones = range(len(names))
    ejes.barh(list(posiciones), scores, color=palette.accent, height=0.62, zorder=3)

    for y, valor in zip(posiciones, scores, strict=True):
        ejes.text(
            valor - 0.4,
            y,
            f"{valor:.0f}",
            va="center",
            ha="right",
            color="#0E1420",
            fontsize=8,
            weight="bold",
            zorder=4,
        )

    ejes.set_yticks(list(posiciones), names, color=TEXT, fontsize=8)
    ejes.invert_yaxis()
    minimo = min(scores)
    ejes.set_xlim(max(0, minimo - 6), min(100, max(scores) + 2))
    ejes.set_xlabel("Parecido de perfil (%)", color=TEXT_MUTED, fontsize=8)
    ejes.grid(axis="x", color=GRID, linewidth=0.7, zorder=1)
    ejes.tick_params(axis="x", colors=TEXT_MUTED, labelsize=7)
    figura.tight_layout()
    return figura


def scouting_plane(
    reference: tuple[str, float, float],
    neighbours: list[tuple[str, float, float]],
    x_label: str,
    y_label: str,
    palette: Palette = DEFAULT,
) -> Figure:
    """Situa al jugador y a sus comparables en un plano de dos familias.

    Es el grafico que convierte una lista de nombres en algo interpretable: no
    dice solo *quien* se parece, sino *por donde*. Dos jugadores con el mismo
    porcentaje de parecido pueden estar uno arriba y otro a la derecha, y para
    un scout esa diferencia lo es todo.

    Las lineas del 50 parten el plano en cuatro cuadrantes, que es como se lee
    un perfil de un vistazo: mucho de esto y poco de aquello.
    """
    figura, ejes = _lienzo(SMALL_SIZE)

    ejes.axvline(50, color=GRID, linewidth=1, zorder=1)
    ejes.axhline(50, color=GRID, linewidth=1, zorder=1)

    for nombre, x, y in neighbours:
        ejes.scatter(x, y, s=52, color=palette.secondary, alpha=0.85, zorder=3)
        ejes.annotate(
            nombre,
            (x, y),
            xytext=(5, 4),
            textcoords="offset points",
            fontsize=7,
            color=TEXT_MUTED,
        )

    nombre, x, y = reference
    ejes.scatter(x, y, s=150, color=palette.accent, edgecolor=TEXT, linewidth=1.2, zorder=4)
    ejes.annotate(
        nombre,
        (x, y),
        xytext=(7, 6),
        textcoords="offset points",
        fontsize=8,
        color=TEXT,
        weight="bold",
    )

    ejes.set_xlim(0, 100)
    ejes.set_ylim(0, 100)
    ejes.set_xlabel(f"{x_label} (percentil)", color=TEXT_MUTED, fontsize=8)
    ejes.set_ylabel(f"{y_label} (percentil)", color=TEXT_MUTED, fontsize=8)
    ejes.grid(color=GRID, linewidth=0.6, alpha=0.6, zorder=0)
    ejes.tick_params(colors=TEXT_MUTED, labelsize=7)
    figura.tight_layout()
    return figura


def squad_age_value(
    players: list[tuple[str, int, float]],
    palette: Palette = DEFAULT,
    peak_age: int = 27,
) -> Figure:
    """Edad frente a valor de mercado de una plantilla.

    Es la lectura de planificacion deportiva de toda la vida, y contesta cosas
    que ninguna tabla ordenada por valor contesta: si el patrimonio del club
    esta en gente que aun va a subir o en gente que ya solo puede bajar, y si
    hay un agujero generacional entre los veteranos y la cantera.

    La linea vertical marca el pico de valor, alrededor de los 27: a la
    izquierda el valor todavia tiende a crecer, a la derecha a caer. No es una
    ley, es donde esta el maximo de la curva en casi todas las posiciones.
    """
    if not players:
        raise ValueError("No hay jugadores con edad y valor conocidos.")

    figura, ejes = _lienzo((5.6, 3.4))
    edades = [p[1] for p in players]
    valores = [p[2] / 1e6 for p in players]

    ejes.axvline(peak_age, color=GRID, linewidth=1, linestyle="--", zorder=1)
    ejes.text(
        peak_age + 0.2,
        max(valores) * 0.95,
        "pico de valor",
        color=TEXT_MUTED,
        fontsize=7,
        va="top",
    )

    ejes.scatter(
        edades,
        valores,
        s=70,
        color=palette.accent,
        alpha=0.85,
        edgecolor=BACKGROUND,
        linewidth=0.8,
        zorder=3,
    )

    # Solo se etiquetan los mas caros: con veinte nombres el grafico se vuelve
    # ilegible y lo que interesa es quien sostiene el patrimonio.
    destacados = sorted(players, key=lambda p: p[2], reverse=True)[:6]
    for nombre, edad, valor in destacados:
        ejes.annotate(
            nombre,
            (edad, valor / 1e6),
            xytext=(5, 3),
            textcoords="offset points",
            fontsize=7,
            color=TEXT,
        )

    ejes.set_xlabel("Edad", color=TEXT_MUTED, fontsize=8)
    ejes.set_ylabel("Valor de mercado (M EUR)", color=TEXT_MUTED, fontsize=8)
    ejes.grid(color=GRID, linewidth=0.6, alpha=0.6, zorder=0)
    ejes.tick_params(colors=TEXT_MUTED, labelsize=7)
    figura.tight_layout()
    return figura


def style_map(data: StyleMapData, title: str, palette: Palette = DEFAULT) -> Figure:
    """Mapa de estilos: territorio frente a altura de presion.

    El eje horizontal es cuanto campo pisa un equipo de verdad —llegadas a zona
    de remate por partido— y no la posesion, que Understat no publica. Es ademas
    un plano mas informativo: acumular pases y pisar el area rival no son lo
    mismo.

    El eje vertical se invierte porque una PPDA baja significa presion alta:
    dejarlo sin invertir situaria a los equipos mas agresivos abajo, que es lo
    contrario de lo que la vista sugiere.
    """
    if not len(data):
        raise ValueError("No hay equipos con posesión y presión conocidas.")

    figura, ejes = _lienzo(MAP_SIZE)

    for cluster in sorted(set(data.clusters)):
        indices = [i for i, valor in enumerate(data.clusters) if valor == cluster]
        ejes.scatter(
            [data.territory[i] for i in indices],
            [data.ppda[i] for i in indices],
            s=90,
            color=OKABE_ITO[cluster % len(OKABE_ITO)],
            # La forma es un segundo canal: con muchos grupos el color solo no
            # llega, y ademas hay quien no distingue algunos pares.
            marker=CLUSTER_MARKERS[cluster % len(CLUSTER_MARKERS)],
            edgecolor=BACKGROUND,
            linewidth=1.2,
            label=data.styles[indices[0]],
            zorder=3,
        )

    for i, equipo in enumerate(data.teams):
        ejes.annotate(
            equipo,
            (data.territory[i], data.ppda[i]),
            xytext=(5, 3),
            textcoords="offset points",
            fontsize=7,
            color=TEXT_MUTED,
        )

    ejes.invert_yaxis()
    ejes.set_xlabel("Llegadas a zona de remate por partido", color=TEXT_MUTED, fontsize=9)
    ejes.set_ylabel("PPDA aproximada (arriba = más presión)", color=TEXT_MUTED, fontsize=9)
    ejes.set_title(title, color=TEXT, weight="bold", fontsize=12)
    ejes.grid(color=GRID, linewidth=0.7, zorder=1)
    ejes.tick_params(colors=TEXT_MUTED, labelsize=8)
    # La leyenda va FUERA del area de dibujo. Dentro tapaba puntos del propio
    # scatter, que en un mapa de dispersion es perder dato para explicar el dato.
    leyenda = ejes.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
        fontsize=7,
        frameon=False,
    )
    for texto in leyenda.get_texts():
        texto.set_color(TEXT)
    figura.tight_layout()
    return figura


def compare(
    data: ComparisonData,
    name_a: str,
    name_b: str,
    subtitle: str,
    palette: Palette = DEFAULT,
) -> Figure:
    """Dibuja a dos jugadores sobre los mismos ejes.

    Es el formato que mas circula en football analytics porque responde de un
    vistazo a la pregunta que de verdad se hace un analista: no "como es este
    jugador", sino "en que se diferencia de aquel".
    """
    if not len(data):
        raise ValueError("Los dos jugadores no comparten ninguna métrica con percentil.")

    color_a, color_b = palette.accent, palette.secondary

    baker = PyPizza(
        params=data.labels,
        background_color=BACKGROUND,
        straight_line_color=GRID,
        straight_line_lw=1,
        last_circle_color=GRID,
        last_circle_lw=1.5,
        other_circle_lw=0,
        inner_circle_size=16,
    )

    figura, ejes = baker.make_pizza(
        data.values_a,
        compare_values=data.values_b,
        figsize=COMPARE_SIZE,
        kwargs_slices={
            "facecolor": color_a,
            "edgecolor": BACKGROUND,
            "zorder": 2,
            "linewidth": 1,
        },
        kwargs_compare={
            "facecolor": color_b,
            "edgecolor": BACKGROUND,
            "zorder": 2,
            "linewidth": 1,
        },
        kwargs_params={"color": TEXT, "fontsize": 8, "va": "center"},
        kwargs_values={
            "color": "#0E1420",
            "fontsize": 8,
            "zorder": 3,
            "bbox": {
                "edgecolor": BACKGROUND,
                "facecolor": color_a,
                "boxstyle": "round,pad=0.15",
                "lw": 1,
            },
        },
        kwargs_compare_values={
            "color": "#0E1420",
            "fontsize": 8,
            "zorder": 3,
            "bbox": {
                "edgecolor": BACKGROUND,
                "facecolor": color_b,
                "boxstyle": "round,pad=0.15",
                "lw": 1,
            },
        },
    )

    figura.text(
        0.515, 0.985, f"{name_a}  vs  {name_b}", size=12, ha="center", color=TEXT, weight="bold"
    )
    figura.text(0.515, 0.955, subtitle, size=8, ha="center", color=TEXT_MUTED)
    figura.text(0.34, 0.015, name_a, size=9, ha="center", color=color_a, weight="bold")
    figura.text(0.66, 0.015, name_b, size=9, ha="center", color=color_b, weight="bold")
    ejes.set_facecolor(BACKGROUND)
    return figura


# Pie que se incrusta en cada PNG exportado. Sin esto, un grafico que circula
# por redes pierde de donde sale: quien lo ve no sabe ni quien lo hizo ni con que
# datos, y eso vale tanto para la atribucion como para que el dato se lea bien.
BRAND = "Fútbol Analytics"
DATA_SOURCE = "Datos: Understat · Transfermarkt"


def to_png(figura: Figure, dpi: int = 200, brand: bool = True) -> bytes:
    """Convierte una figura en un PNG listo para publicar.

    Se fija el color de fondo explícitamente porque `savefig` usa blanco por
    defecto y perdería el fondo del gráfico, dejando un marco blanco alrededor
    del círculo. A 200 ppp la imagen aguanta bien en una publicación sin pesar
    de más.

    La marca y la fuente van incrustadas en la imagen, no como texto aparte: un
    gráfico se comparte solo, sin el mensaje que lo acompañaba, y sin el pie
    nadie sabe de dónde sale ni con qué datos está hecho.
    """
    if brand:
        _firmar(figura)

    buffer = io.BytesIO()
    figura.savefig(
        buffer,
        format="png",
        dpi=dpi,
        bbox_inches="tight",
        facecolor=figura.get_facecolor(),
    )
    return buffer.getvalue()


def _firmar(figura: Figure) -> None:
    """Pone la marca y la fuente en el pie de la figura.

    Se comprueba antes de escribir para no firmar dos veces: la misma figura se
    puede exportar varias veces si el usuario pulsa descargar más de una vez.
    """
    if getattr(figura, "_firmada", False):
        return

    figura.text(0.01, 0.008, BRAND, size=7, ha="left", color=TEXT_MUTED, weight="bold")
    figura.text(0.99, 0.008, DATA_SOURCE, size=6.5, ha="right", color=TEXT_MUTED)
    figura._firmada = True


def _lienzo(size: tuple[float, float]) -> tuple[Figure, plt.Axes]:
    """Figura con el fondo oscuro y los bordes del tema ya aplicados."""
    figura, ejes = plt.subplots(figsize=size)
    figura.patch.set_facecolor(BACKGROUND)
    ejes.set_facecolor(BACKGROUND)
    for lado in ejes.spines.values():
        lado.set_color(GRID)
    return figura, ejes


def shot_map(
    shots: list[dict],
    title: str,
    palette: Palette = DEFAULT,
    conceded: bool = False,
) -> Figure:
    """Mapa de tiros sobre medio campo.

    Es el gráfico más reconocible de la analítica de fútbol moderna, y aquí
    responde a algo que ningún agregado responde: un mismo npxG por 90 puede
    venir de tres remates claros o de quince disparos lejanos, y para un scout
    no son el mismo futbolista.

    **El tamaño del punto es el xG del tiro**, no un valor fijo: es lo que hace
    visible de un vistazo que un jugador vive de ocasiones grandes o de muchas
    pequeñas. El color separa el gol del resto.

    Se dibuja medio campo porque prácticamente ningún tiro sale de la mitad
    propia, y con el campo entero los remates se apelmazan en un rincón.

    Con `conceded` cambian las etiquetas y el color del gol: un gol no significa
    lo mismo cuando se remata que cuando se recibe, y pintar de color de marca un
    gol encajado se leería como un logro.
    """
    if not shots:
        raise ValueError("Este jugador no tiene tiros cargados.")

    campo = VerticalPitch(
        pitch_type="opta",
        half=True,
        pitch_color=BACKGROUND,
        line_color=GRID,
        linewidth=1.1,
        pad_bottom=-8,
    )
    figura, ejes = campo.draw(figsize=(4.6, 4.4))
    figura.patch.set_facecolor(BACKGROUND)

    color_gol = CATEGORY_COLORS[FINISHING] if conceded else palette.accent
    etiqueta_gol = "Gol encajado" if conceded else "Gol"
    etiqueta_resto = "Remate parado o fallado" if conceded else "Sin gol"

    # Understat normaliza a 0-1 y `opta` espera 0-100.
    x = [(s["location_x"] or 0) * 100 for s in shots]
    y = [(s["location_y"] or 0) * 100 for s in shots]
    tamanos = [max(18.0, (s["xg"] or 0.0) * 900) for s in shots]
    goles = [s["result"] == "Goal" for s in shots]

    campo.scatter(
        [v for v, g in zip(x, goles, strict=True) if not g],
        [v for v, g in zip(y, goles, strict=True) if not g],
        s=[v for v, g in zip(tamanos, goles, strict=True) if not g],
        ax=ejes,
        color=palette.secondary,
        alpha=0.45,
        edgecolor=BACKGROUND,
        linewidth=0.6,
        zorder=2,
        label=etiqueta_resto,
    )
    campo.scatter(
        [v for v, g in zip(x, goles, strict=True) if g],
        [v for v, g in zip(y, goles, strict=True) if g],
        s=[v for v, g in zip(tamanos, goles, strict=True) if g],
        ax=ejes,
        color=color_gol,
        alpha=0.95,
        edgecolor=TEXT,
        linewidth=0.8,
        zorder=3,
        label=etiqueta_gol,
    )

    figura.text(0.5, 0.965, title, size=11, ha="center", color=TEXT, weight="bold")
    figura.text(
        0.5,
        0.935,
        "El tamaño del punto es el xG del remate",
        size=7.5,
        ha="center",
        color=TEXT_MUTED,
    )
    leyenda = ejes.legend(loc="lower center", fontsize=7, frameon=False, ncol=2)
    for texto in leyenda.get_texts():
        texto.set_color(TEXT_MUTED)
    return figura


def mirror_bars(
    data: ComparisonData,
    name_a: str,
    name_b: str,
    palette: Palette = DEFAULT,
) -> Figure:
    """Dos jugadores en barras enfrentadas, ordenadas por diferencia.

    Complementa al pizza comparado y responde a otra pregunta. El pizza dice
    cómo es cada uno; esto dice **dónde está la diferencia**, que es lo que un
    scout quiere saber cuando ya sabe que los dos le valen.

    El orden lo manda la diferencia absoluta y no la plantilla, al revés que en
    el pizza: aquí las porciones no tienen que caer siempre en el mismo sitio,
    porque no se comparan dos gráficos entre sí sino dos jugadores dentro del
    mismo. Poner arriba la mayor diferencia hace que la respuesta se lea en la
    primera línea.

    Los dos ejes van de 0 a 100 hacia fuera desde el centro, así que la longitud
    de cada barra es directamente el percentil y las dos mitades son
    comparables.
    """
    if not len(data):
        raise ValueError("Los dos jugadores no comparten ninguna métrica con percentil.")

    diferencias = [b - a for a, b in zip(data.values_a, data.values_b, strict=True)]
    orden = sorted(range(len(data)), key=lambda i: abs(diferencias[i]))

    etiquetas = [data.labels[i] for i in orden]
    izquierda = [data.values_a[i] for i in orden]
    derecha = [data.values_b[i] for i in orden]

    alto = max(2.6, 0.42 * len(etiquetas) + 1.0)
    figura, ejes = _lienzo((6.4, alto))
    posiciones = range(len(etiquetas))

    # El jugador A crece hacia la izquierda, el B hacia la derecha.
    ejes.barh(
        list(posiciones), [-v for v in izquierda], color=palette.accent, height=0.66, zorder=3
    )
    ejes.barh(list(posiciones), derecha, color=palette.secondary, height=0.66, zorder=3)

    for y, (a, b) in enumerate(zip(izquierda, derecha, strict=True)):
        ejes.text(-a - 2, y, f"{a}", va="center", ha="right", color=TEXT_MUTED, fontsize=7.5)
        ejes.text(b + 2, y, f"{b}", va="center", ha="left", color=TEXT_MUTED, fontsize=7.5)

    ejes.axvline(0, color=GRID, linewidth=1.2, zorder=2)
    ejes.set_yticks(list(posiciones), etiquetas, color=TEXT, fontsize=8)
    ejes.set_xlim(-118, 118)
    # Las marcas del eje se etiquetan en valor absoluto: el signo solo indica de
    # quién es la barra, no un valor negativo.
    marcas = [-100, -50, 0, 50, 100]
    ejes.set_xticks(marcas, [str(abs(m)) for m in marcas], color=TEXT_MUTED, fontsize=7)
    ejes.set_xlabel("Percentil", color=TEXT_MUTED, fontsize=8)
    ejes.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.5, zorder=1)
    ejes.tick_params(colors=TEXT_MUTED)

    figura.text(0.28, 0.965, name_a, size=9, ha="center", color=palette.accent, weight="bold")
    figura.text(0.74, 0.965, name_b, size=9, ha="center", color=palette.secondary, weight="bold")
    figura.tight_layout(rect=(0, 0, 1, 0.94))
    return figura


def cumulative_goals(
    matches: list[dict],
    title: str,
    palette: Palette = DEFAULT,
) -> Figure:
    """Goles acumulados frente a xG acumulado a lo largo de la temporada.

    Es el gráfico honesto cuando hay pocas jornadas. Una media móvil de tres
    partidos sobre cinco es prácticamente el dato bruto con otro nombre, y
    sugiere una tendencia donde solo hay ruido; la curva acumulada no promete
    tendencia, solo enseña cómo se ha llegado hasta aquí.

    Y ahí está lo que ninguna cifra de temporada dice: si un sobrerrendimiento
    viene de un partido suelto —las dos líneas se separan de golpe y luego van
    en paralelo— o de todos, que es cuando empieza a merecer atención.
    """
    if not matches:
        raise ValueError("Este jugador no tiene partidos cargados.")

    figura, ejes = _lienzo((5.6, 3.2))
    x = range(1, len(matches) + 1)
    goles = [m["cumulative_goals"] for m in matches]
    xg = [m["cumulative_xg"] for m in matches]

    ejes.plot(
        x,
        xg,
        color=palette.secondary,
        linewidth=2,
        marker="o",
        markersize=4,
        label="xG acumulado",
        zorder=3,
    )
    ejes.plot(
        x,
        goles,
        color=palette.accent,
        linewidth=2.2,
        marker="o",
        markersize=4,
        label="Goles",
        zorder=4,
    )
    # El area entre las dos es la diferencia: verla pintada evita tener que
    # restar dos curvas a ojo.
    ejes.fill_between(x, goles, xg, color=palette.accent, alpha=0.12, zorder=2)

    ejes.set_xticks(list(x), [str(i) for i in x], color=TEXT_MUTED, fontsize=7)
    ejes.set_xlabel("Partidos jugados", color=TEXT_MUTED, fontsize=8)
    ejes.set_ylabel("Acumulado", color=TEXT_MUTED, fontsize=8)
    ejes.set_title(title, color=TEXT, fontsize=10, weight="bold")
    ejes.grid(color=GRID, linewidth=0.6, alpha=0.6, zorder=1)
    ejes.tick_params(colors=TEXT_MUTED, labelsize=7)
    leyenda = ejes.legend(loc="upper left", fontsize=7.5, frameon=False)
    for texto in leyenda.get_texts():
        texto.set_color(TEXT_MUTED)
    figura.tight_layout()
    return figura


def slope_chart(
    labels: list[str],
    before: list[int],
    after: list[int],
    season_before: str,
    season_after: str,
    palette: Palette = DEFAULT,
) -> Figure:
    """Cambio de percentil entre dos temporadas.

    **Es un slope chart y no un gráfico de líneas a propósito.** Con dos
    temporadas hay dos puntos, y dos puntos no son una tendencia: una línea que
    los une sugiere una trayectoria que no está en los datos. Un slope
    representa lo que de verdad hay, que es un cambio entre dos observaciones.

    El color de cada línea dice la dirección —sube o baja— y el grosor, cuánto:
    así los cambios grandes destacan sin tener que leer los números.
    """
    if not labels:
        raise ValueError("No hay métricas comparables entre las dos temporadas.")

    alto = max(3.2, 0.34 * len(labels) + 1.4)
    figura, ejes = _lienzo((5.4, alto))

    for etiqueta, antes, despues in zip(labels, before, after, strict=True):
        cambio = despues - antes
        color = palette.accent if cambio >= 0 else CATEGORY_COLORS[FINISHING]
        ejes.plot(
            [0, 1],
            [antes, despues],
            color=color,
            linewidth=max(1.0, min(3.2, abs(cambio) / 12)),
            marker="o",
            markersize=4,
            alpha=0.9,
            zorder=3,
        )
        ejes.text(
            -0.04,
            antes,
            f"{etiqueta}  {antes}",
            ha="right",
            va="center",
            fontsize=7,
            color=TEXT_MUTED,
        )
        ejes.text(1.04, despues, f"{despues}", ha="left", va="center", fontsize=7, color=TEXT)

    ejes.set_xlim(-0.75, 1.3)
    ejes.set_ylim(-5, 105)
    ejes.set_xticks([0, 1], [season_before, season_after], color=TEXT, fontsize=9)
    ejes.set_ylabel("Percentil", color=TEXT_MUTED, fontsize=8)
    ejes.tick_params(axis="y", colors=TEXT_MUTED, labelsize=7)
    ejes.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.5, zorder=1)
    for lado in ("top", "right", "bottom"):
        ejes.spines[lado].set_visible(False)
    figura.tight_layout()
    return figura
