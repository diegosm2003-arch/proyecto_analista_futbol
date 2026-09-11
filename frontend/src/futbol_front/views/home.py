"""Portada: por donde se entra a la plataforma.

Existe porque las dos vistas responden a preguntas distintas y no encadenadas.
Un analista entra sabiendo si viene a mirar a un futbolista o a un equipo, y
cayendo directamente en la de jugadores tenia que darse cuenta de que habia otra
y buscarla en el menu.

Ademas es donde tiene sentido decir de que va esto y con que datos, antes de que
alguien lea un percentil sin saber contra quien esta calculado. En las pantallas
de trabajo esa explicacion estorbaria; aqui es lo primero que se lee.
"""

from __future__ import annotations

import streamlit as st

from futbol_front import branding
from futbol_front.client import ApiError
from futbol_front.presentation import season_label
from futbol_front.state import cached_catalog, cached_insights
from futbol_front.theme import apply

# Clave en el estado de sesion con la vista elegida. La navegacion no usa las
# paginas de Streamlit porque desde la portada se entra con contexto (el ambito
# elegido), y una pagina nueva lo perderia.
DESTINO = "destino"

JUGADORES = "jugadores"
EQUIPOS = "equipos"
SCOUTING = "scouting"
CHAT = "chat"


def ir_a(destino: str) -> None:
    """Cambia de vista sin recargar la aplicacion."""
    st.session_state[DESTINO] = destino


def destino_actual() -> str | None:
    return st.session_state.get(DESTINO)


def render() -> None:
    """Pantalla de entrada."""
    apply(None)

    st.markdown(
        f"""
        <div style="padding: 2.2rem 0 0.6rem 0;">
          <div class="marca-portada">{branding.logo_html(64)}</div>
          <h1 style="font-size: 3rem; margin: .6rem 0 .2rem 0;">Fútbol Analytics</h1>
          <p style="color:#8D9AB4; font-size:1.05rem; max-width: 46rem; line-height:1.6;">
            Percentiles por posición frente a las cinco grandes ligas, perfiles de rol,
            estilo de equipo y valor de mercado. Cada número viene con el contexto que
            hace falta para no leerlo mal.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Estrechas y altas, con el icono arriba: una ficha ancha y baja se lee como
    # una barra de navegacion, no como una eleccion.
    jugadores, equipos, scouting, chat = st.columns(4, gap="large")

    _tarjeta(
        jugadores,
        icono=ICONO_JUGADOR,
        titulo="Jugadores",
        texto=(
            "Perfil de percentiles, rol asignado, valor de mercado y carrera. "
            "Y quien más juega así en las Big 5."
        ),
        etiqueta="Analizar jugadores",
        destino=JUGADORES,
        principal=True,
    )
    _tarjeta(
        equipos,
        icono=ICONO_EQUIPO,
        titulo="Equipos",
        texto=(
            "Estilo de juego por territorio y altura de presión, con los equipos "
            "agrupados por como compiten y no por lo que ganan."
        ),
        etiqueta="Analizar equipos",
        destino=EQUIPOS,
        principal=False,
    )
    _tarjeta(
        scouting,
        icono=ICONO_BUSCADOR,
        titulo="Scouting",
        texto=(
            "Quién rinde por encima de un percentil y además encaja por edad, "
            "contrato y precio. No quién es bueno: a quién se puede ir a buscar."
        ),
        etiqueta="Buscar jugadores",
        destino=SCOUTING,
        principal=False,
    )
    _tarjeta(
        chat,
        icono=ICONO_CHAT,
        titulo="Asistente",
        texto=(
            "Pregunta en lenguaje natural y recibe la misma respuesta que darían "
            "estos datos en una pantalla, con las fuentes que ha consultado."
        ),
        etiqueta="Preguntar",
        destino=CHAT,
        principal=False,
    )

    _hallazgos()


# Iconos en SVG y no con la fuente de iconos de Streamlit: dentro de un bloque
# de HTML propio no hay garantia de que esa fuente este cargada, y un icono que
# no carga deja un nombre en ingles suelto en mitad de la tarjeta. Un SVG en
# linea no depende de nada y hereda el color del tema.
ICONO_JUGADOR = (
    '<svg viewBox="0 0 24 24" width="56" height="56" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="13.5" cy="4" r="2"/>'
    '<path d="M12.5 21l-1-6 3-2.5-1-4.5"/>'
    '<path d="M13.5 8l3.5 2 2.5-1"/>'
    '<path d="M11.5 8L8 10l-2 4"/>'
    '<path d="M13.5 15l3 6"/>'
    "</svg>"
)

ICONO_EQUIPO = (
    '<svg viewBox="0 0 24 24" width="56" height="56" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M12 2.5l7.5 2.5v6c0 4.6-3.1 8.6-7.5 10-4.4-1.4-7.5-5.4-7.5-10v-6z"/>'
    '<path d="M12 7.5l1.6 3.2 3.4.5-2.5 2.4.6 3.4-3.1-1.6-3.1 1.6.6-3.4-2.5-2.4 3.4-.5z"/>'
    "</svg>"
)


ICONO_BUSCADOR = (
    '<svg viewBox="0 0 24 24" width="56" height="56" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="10.5" cy="10.5" r="6.5"/>'
    '<path d="M15.4 15.4L21 21"/>'
    '<path d="M7.6 10.5l2 2 3.8-4"/>'
    "</svg>"
)

ICONO_CHAT = (
    '<svg viewBox="0 0 24 24" width="56" height="56" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<path d="M4 5.5h16v10.5H9l-4 3.5v-3.5H4z"/>'
    '<path d="M8 9.5h8M8 12.5h5"/>'
    "</svg>"
)


def _tarjeta(
    columna,
    icono: str,
    titulo: str,
    texto: str,
    etiqueta: str,
    destino: str,
    principal: bool,
) -> None:
    """Una de las dos puertas de entrada."""
    with columna, st.container(border=True):
        st.markdown(
            f'<div class="tarjeta-ambito">'
            f'<div class="icono">{icono}</div>'
            f"<h3>{titulo}</h3><p>{texto}</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.button(
            etiqueta,
            type="primary" if principal else "secondary",
            width="stretch",
            on_click=ir_a,
            args=(destino,),
        )


def _hallazgos() -> None:
    """Lo que los datos cargados tienen de interesante hoy.

    Sustituye a un recuento de temporadas y ligas, que eran metadatos de
    instalacion y no analisis. El criterio de valor del proyecto no es tecnico:
    un analisis vale si se puede resumir en una frase que a un aficionado
    avanzado le resulte interesante, y la portada es donde eso tiene que
    demostrarse antes que en ningun otro sitio.
    """
    try:
        catalogo = cached_catalog()
    except ApiError as error:
        st.error(f"La API no responde: {error}")
        return

    if not catalogo["seasons"]:
        st.warning("No hay datos cargados todavía.")
        return

    temporada = catalogo["seasons"][-1]
    try:
        hallazgos = cached_insights(temporada)
    except ApiError as error:
        st.error(str(error))
        return

    st.divider()
    st.subheader(f"Lo que dicen los datos · {season_label(temporada)}")
    st.caption(
        "Calculado sobre las cinco grandes ligas. Cada dato viene con como hay que "
        "leerlo, porque casi todos los extremos de una temporada empezada son ruido."
    )

    if not hallazgos:
        st.info("Aun no hay suficientes datos cargados para sacar conclusiones.")
        return

    for inicio_fila in range(0, len(hallazgos), 2):
        columnas = st.columns(2, gap="large")
        for columna, hallazgo in zip(
            columnas, hallazgos[inicio_fila : inicio_fila + 2], strict=False
        ):
            with columna, st.container(border=True):
                st.markdown(
                    f'<div class="hallazgo">'
                    f'<div class="tema">{hallazgo["topic"]}</div>'
                    f'<div class="titular">{hallazgo["headline"]}</div>'
                    f'<div class="detalle">{hallazgo["detail"]}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if hallazgo["caveat"]:
                    st.caption(f":orange[Ojo: {hallazgo['caveat']}]")


def _que_hay_cargado() -> None:
    """Que datos hay, antes de que alguien lea un percentil.

    Se ensena en la portada y no en las pantallas de trabajo porque es lo que
    determina si un percentil significa algo: contra cuantas ligas se compara y
    de que temporada.
    """
    try:
        catalogo = cached_catalog()
    except ApiError as error:
        st.error(f"La API no responde: {error}")
        return

    st.divider()
    columnas = st.columns(3)
    columnas[0].metric("Temporadas", len(catalogo["seasons"]))
    columnas[1].metric("Ligas", len(catalogo["leagues"]))
    columnas[2].metric("Umbral de minutos", catalogo["min_minutes"])

    st.caption(
        "Los percentiles se calculan contra **las cinco grandes ligas**, no solo contra "
        "LaLiga: con una sola liga la muestra por posición se queda corta y el percentil "
        "acaba midiendo el ruido. El filtro por liga se aplica después de calcular."
    )
