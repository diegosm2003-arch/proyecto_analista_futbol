"""Tema visual de la interfaz, con una paleta por liga.

Streamlit fija su tema al arrancar, en un fichero de configuracion, asi que no
se puede cambiar por liga desde el codigo. Lo que si se puede es inyectar CSS en
cada pasada, que es lo que se hace aqui: el tema base es oscuro y cada liga
reasigna un punado de variables de color.

**La liga tine, no decora.** Un analista pasa horas mirando estas pantallas y
alterna entre competiciones; que el acento cambie es lo que le dice de un
vistazo en cual esta sin tener que leer el filtro. Por eso el cambio es de color
de acento y no de estructura: la disposicion se mantiene identica entre ligas
para que dos capturas sigan siendo comparables.

Los colores salen de la identidad de cada competicion, pero rebajados: un rojo
de escudo a pantalla completa sobre fondo oscuro cansa la vista en diez minutos.
Se usan como acento sobre una base neutra, no como fondo.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True, slots=True)
class Palette:
    """Colores de una liga.

    `accent` es el color de marca; `accent_soft` su version apagada para fondos
    y bordes, donde el color saturado molestaria.
    """

    name: str
    accent: str
    accent_soft: str
    # Segundo color, para la serie de comparacion y el rival en los graficos.
    secondary: str


# Base oscura comun. No cambia entre ligas: lo que cambia es el acento.
INK = "#0E1420"
SURFACE = "#161D2B"
SURFACE_HIGH = "#1E273A"
BORDER = "#2A344A"
TEXT = "#E9EDF5"
TEXT_MUTED = "#8D9AB4"

DEFAULT = Palette("Big 5", accent="#F5C518", accent_soft="#3A3316", secondary="#4C8DFF")

PALETTES: dict[str, Palette] = {
    # Rojo y oro sobre azul noche.
    "ESP-La Liga": Palette("LaLiga", accent="#FF4B55", accent_soft="#3A1D22", secondary="#F5C518"),
    # El morado de la Premier, con el turquesa de su segunda gama.
    "ENG-Premier League": Palette(
        "Premier League", accent="#B14BFF", accent_soft="#2C1B3D", secondary="#00E1C4"
    ),
    # El azul de la Serie A.
    "ITA-Serie A": Palette("Serie A", accent="#3D8BFF", accent_soft="#16273F", secondary="#7ED957"),
    # Rojo sobre carbon, como la identidad alemana.
    "GER-Bundesliga": Palette(
        "Bundesliga", accent="#E8353C", accent_soft="#33191B", secondary="#F5C518"
    ),
    # Azul electrico de la Ligue 1.
    "FRA-Ligue 1": Palette("Ligue 1", accent="#00C2FF", accent_soft="#12303C", secondary="#FF9F1C"),
}


def palette(league: str | None) -> Palette:
    """Paleta de una liga. La de por defecto cuando se miran todas a la vez."""
    if league is None:
        return DEFAULT
    return PALETTES.get(league, DEFAULT)


def apply(league: str | None = None) -> Palette:
    """Inyecta el CSS del tema y devuelve la paleta en uso.

    Se llama en cada pasada porque Streamlit reconstruye el DOM entero con cada
    interaccion; el navegador no repinta si el CSS no ha cambiado, asi que no
    cuesta nada.
    """
    p = palette(league)
    st.markdown(_css(p), unsafe_allow_html=True)
    return p


def _css(p: Palette) -> str:
    return f"""
<style>
:root {{
    --acento: {p.accent};
    --acento-suave: {p.accent_soft};
    --secundario: {p.secondary};
    --tinta: {INK};
    --superficie: {SURFACE};
    --superficie-alta: {SURFACE_HIGH};
    --borde: {BORDER};
    --texto: {TEXT};
    --texto-apagado: {TEXT_MUTED};
}}

.stApp {{
    background:
        radial-gradient(1200px 600px at 15% -10%, {p.accent_soft} 0%, transparent 60%),
        {INK};
    color: {TEXT};
}}

/* La barra lateral solo guarda el estado de los datos: los filtros se han
   subido arriba, donde se usan. */
section[data-testid="stSidebar"] {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}

h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.02em; }}
h1 {{ font-weight: 800; }}

/* Barra de filtros: una cinta fija arriba, separada del contenido. */
.barra-filtros {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 0.75rem 1rem 0.25rem 1rem;
    margin-bottom: 1.25rem;
}}

/* Tarjetas de la portada y de los paneles. */
.tarjeta {{
    background: linear-gradient(160deg, {SURFACE_HIGH} 0%, {SURFACE} 100%);
    border: 1px solid {BORDER};
    border-radius: 16px;
    padding: 1.25rem 1.4rem;
    height: 100%;
}}
.tarjeta h3 {{ margin: 0 0 .35rem 0; font-size: 1.15rem; }}
.tarjeta p {{ color: {TEXT_MUTED}; margin: 0; font-size: .9rem; line-height: 1.5; }}

/* Cinta de identidad de la liga. */
.cinta-liga {{
    display: inline-flex; align-items: center; gap: .5rem;
    background: {p.accent_soft};
    color: {p.accent};
    border: 1px solid {p.accent};
    border-radius: 999px;
    padding: .2rem .8rem;
    font-size: .78rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .06em;
}}

/* Cifras destacadas. */
div[data-testid="stMetric"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: .7rem .9rem;
}}
div[data-testid="stMetricValue"] {{ color: {p.accent}; font-size: 1.4rem; }}
div[data-testid="stMetricLabel"] {{ color: {TEXT_MUTED}; }}

/* Pestanas. */
button[data-baseweb="tab"] {{ color: {TEXT_MUTED}; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {p.accent}; }}
div[data-baseweb="tab-highlight"] {{ background-color: {p.accent}; }}

/* Controles. */
div[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input {{
    background-color: {SURFACE_HIGH};
    border-color: {BORDER};
    color: {TEXT};
}}
.stButton button {{
    background: {SURFACE_HIGH};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-weight: 600;
}}
.stButton button:hover {{ border-color: {p.accent}; color: {p.accent}; }}
.stButton button[kind="primary"] {{
    background: {p.accent};
    border-color: {p.accent};
    color: {INK};
}}

/* Tablas y expansores. */
div[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 12px; }}
details, div[data-testid="stExpander"] {{
    background: {SURFACE};
    border: 1px solid {BORDER} !important;
    border-radius: 12px;
}}

/* El panel de detalle que acompana al grafico. */
.panel-detalle {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-left: 3px solid {p.accent};
    border-radius: 12px;
    padding: .9rem 1rem;
    margin-bottom: .6rem;
}}
.panel-detalle .titulo {{
    color: {TEXT_MUTED}; font-size: .72rem; text-transform: uppercase;
    letter-spacing: .07em; margin-bottom: .15rem;
}}
.panel-detalle .valor {{ color: {TEXT}; font-size: .95rem; font-weight: 600; }}
</style>
"""
