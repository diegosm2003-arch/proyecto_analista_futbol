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


# Logo de cada competicion. La URL se construye con el identificador que usa
# Transfermarkt, que es la misma fuente de la que salen los escudos de club: asi
# los dos pasos del navegador tienen el mismo aspecto y no hay que mezclar
# proveedores de imagenes.
LEAGUE_LOGOS: dict[str, str] = {
    "ESP-La Liga": "https://tmssl.akamaized.net/images/logo/header/es1.png",
    "ENG-Premier League": "https://tmssl.akamaized.net/images/logo/header/gb1.png",
    "ITA-Serie A": "https://tmssl.akamaized.net/images/logo/header/it1.png",
    "GER-Bundesliga": "https://tmssl.akamaized.net/images/logo/header/l1.png",
    "FRA-Ligue 1": "https://tmssl.akamaized.net/images/logo/header/fr1.png",
}


# Competiciones que aun no estan cargadas. Se ensenan atenuadas porque una
# rejilla con cinco fichas y nada mas no dice si eso es todo lo que habra.
#
# **La primera es la unica alcanzable hoy**: Understat, que es la fuente de las
# estadisticas, publica las cinco grandes y la liga rusa, y nada mas. Las otras
# necesitan una fuente que el proyecto todavia no tiene, asi que son una
# intencion y no una fecha. Esta escrito tambien en el README para que no se lea
# como una promesa.
UPCOMING_LEAGUES: tuple[tuple[str, str], ...] = (
    ("Premier rusa", "https://tmssl.akamaized.net/images/logo/header/ru1.png"),
    ("Primeira Liga", "https://tmssl.akamaized.net/images/logo/header/po1.png"),
    ("Eredivisie", "https://tmssl.akamaized.net/images/logo/header/nl1.png"),
    ("Championship", "https://tmssl.akamaized.net/images/logo/header/gb2.png"),
    ("Jupiler Pro League", "https://tmssl.akamaized.net/images/logo/header/be1.png"),
    ("Superliga turca", "https://tmssl.akamaized.net/images/logo/header/tr1.png"),
)


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
    """CSS del tema.

    Se limita a lo que el tema base de `.streamlit/config.toml` no puede hacer:
    el acento por liga y los cuatro bloques propios. Todo lo demas —controles,
    tablas, expansores, barra lateral— lo pinta Streamlit con el tema base, que
    es lo unico que garantiza que no quede texto oscuro sobre fondo oscuro.

    Antes esto intentaba repintar los controles desde fuera, apuntando a los
    `data-baseweb` de Streamlit. Es fragil por definicion: son detalles internos
    de la libreria y basta con que cambien de version para que la pantalla salga
    a medio pintar, que es justo lo que pasaba.
    """
    return f"""
<style>
:root {{
    --acento: {p.accent};
    --acento-suave: {p.accent_soft};
    --secundario: {p.secondary};
    --superficie: {SURFACE};
    --borde: {BORDER};
    --texto-apagado: {TEXT_MUTED};
}}

/* Un degradado tenue con el color de la liga, sobre el fondo del tema base. */
.stApp {{
    background:
        radial-gradient(1100px 520px at 12% -8%, {p.accent_soft} 0%, transparent 62%),
        {INK};
}}

h1, h2, h3, h4 {{ letter-spacing: -0.02em; }}
h1 {{ font-weight: 800; }}

/* Cifras destacadas: el valor toma el color de la liga. */
div[data-testid="stMetricValue"] {{ color: {p.accent}; font-size: 1.35rem; }}

/* Pestanas activas, también con el acento. */
button[data-baseweb="tab"][aria-selected="true"] {{ color: {p.accent}; }}
div[data-baseweb="tab-highlight"] {{ background-color: {p.accent}; }}

/* Boton principal. */
.stButton button[kind="primary"] {{
    background: {p.accent};
    border-color: {p.accent};
    color: {INK};
    font-weight: 700;
}}
.stButton button:hover {{ border-color: {p.accent}; }}

/* Logotipo: toma el acento de la liga a través de currentColor. */
.logotipo {{ color: {p.accent}; display: inline-flex; }}
.logotipo svg, .logotipo img {{ width: 100%; height: 100%; }}
.marca-logo {{ display: flex; align-items: center; justify-content: flex-start; }}
.marca-portada {{ margin-bottom: .4rem; }}

/* Cinta con el nombre de la liga. */
.cinta-liga {{
    display: inline-flex; align-items: center; gap: .5rem;
    background: {p.accent_soft};
    color: {p.accent};
    border: 1px solid {p.accent};
    border-radius: 999px;
    padding: .18rem .8rem;
    font-size: .75rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .06em;
}}

/* Ficha de la portada: alta y estrecha, con el icono arriba. */
.tarjeta-ambito {{
    text-align: center;
    padding: 1.6rem 1.2rem 0.6rem 1.2rem;
}}
.tarjeta-ambito .icono {{
    color: {p.accent};
    line-height: 0; margin-bottom: .9rem;
    filter: drop-shadow(0 0 16px {p.accent_soft});
}}
.tarjeta-ambito h3 {{ margin: 0 0 .5rem 0; font-size: 1.3rem; }}
.tarjeta-ambito p {{
    color: {TEXT_MUTED}; margin: 0 auto; font-size: .92rem;
    line-height: 1.55; max-width: 22rem;
}}

/* Ficha de una liga o un equipo en el navegador de tres pasos. */
.ficha-escudo {{
    text-align: center; padding: .4rem 0 .2rem 0;
}}
.ficha-escudo img {{ height: 72px; width: auto; object-fit: contain; }}
.ficha-escudo .sin-escudo {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 72px; height: 72px; border-radius: 14px;
    background: {p.accent_soft}; color: {p.accent};
    font-weight: 800; font-size: 1.5rem;
}}
.ficha-escudo .nombre {{
    margin-top: .55rem; font-size: .92rem; font-weight: 600;
    color: {TEXT}; line-height: 1.25;
}}
.ficha-escudo .dato {{ color: {TEXT_MUTED}; font-size: .78rem; }}

/* Liga que aún no está cargada: en sombra, para que se lea como un anuncio y
   no como algo en lo que se pueda entrar. */
.ficha-proxima {{ text-align: center; padding: .5rem 0 .3rem 0; opacity: .38; }}
.ficha-proxima img {{
    height: 56px; width: auto; object-fit: contain;
    filter: grayscale(1) brightness(1.6);
}}
.ficha-proxima .nombre {{
    margin-top: .5rem; font-size: .84rem; font-weight: 600; color: {TEXT};
}}
.ficha-proxima .etiqueta {{
    margin-top: .2rem; font-size: .68rem; text-transform: uppercase;
    letter-spacing: .08em; color: {TEXT_MUTED};
}}

/* Hallazgo de la portada. */
.hallazgo {{ padding: .3rem .1rem; }}
.hallazgo .tema {{
    color: {p.accent}; font-size: .68rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .09em; margin-bottom: .4rem;
}}
.hallazgo .titular {{
    color: {TEXT}; font-size: 1.02rem; font-weight: 600; line-height: 1.4;
}}
.hallazgo .detalle {{
    color: {TEXT_MUTED}; font-size: .85rem; margin-top: .35rem; line-height: 1.45;
}}

/* Panel de lectura que acompana a un gráfico. */
.panel-detalle {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-left: 3px solid {p.accent};
    border-radius: 10px;
    padding: .7rem .85rem;
    margin-bottom: .5rem;
}}
.panel-detalle .título {{
    color: {TEXT_MUTED}; font-size: .7rem; text-transform: uppercase;
    letter-spacing: .07em; margin-bottom: .15rem;
}}
.panel-detalle .valor {{ color: {TEXT}; font-size: .92rem; font-weight: 600; }}
</style>
"""
