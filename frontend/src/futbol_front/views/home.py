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

from futbol_front.client import ApiError
from futbol_front.state import cached_catalog
from futbol_front.theme import apply

# Clave en el estado de sesion con la vista elegida. La navegacion no usa las
# paginas de Streamlit porque desde la portada se entra con contexto (el ambito
# elegido), y una pagina nueva lo perderia.
DESTINO = "destino"

JUGADORES = "jugadores"
EQUIPOS = "equipos"


def ir_a(destino: str) -> None:
    """Cambia de vista sin recargar la aplicacion."""
    st.session_state[DESTINO] = destino


def destino_actual() -> str | None:
    return st.session_state.get(DESTINO)


def render() -> None:
    """Pantalla de entrada."""
    apply(None)

    st.markdown(
        """
        <div style="padding: 2.2rem 0 0.6rem 0;">
          <div class="cinta-liga">Big 5 &middot; Temporada en curso</div>
          <h1 style="font-size: 3rem; margin: .6rem 0 .2rem 0;">Futbol Analytics</h1>
          <p style="color:#8D9AB4; font-size:1.05rem; max-width: 46rem; line-height:1.6;">
            Percentiles por posicion frente a las cinco grandes ligas, perfiles de rol,
            estilo de equipo y valor de mercado. Cada numero viene con el contexto que
            hace falta para no leerlo mal.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    izquierda, derecha = st.columns(2, gap="large")

    with izquierda:
        st.markdown(
            """
            <div class="tarjeta">
              <h3>Jugadores</h3>
              <p>Perfil de percentiles, rol asignado, valor de mercado y carrera.
              Y quien mas juega asi en las Big 5.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            "Analizar jugadores",
            type="primary",
            width="stretch",
            on_click=ir_a,
            args=(JUGADORES,),
        )

    with derecha:
        st.markdown(
            """
            <div class="tarjeta">
              <h3>Equipos</h3>
              <p>Estilo de juego por posesion y altura de presion, con los equipos
              agrupados por como compiten y no por lo que ganan.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            "Analizar equipos",
            width="stretch",
            on_click=ir_a,
            args=(EQUIPOS,),
        )

    _que_hay_cargado()


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
        "LaLiga: con una sola liga la muestra por posicion se queda corta y el percentil "
        "acaba midiendo el ruido. El filtro por liga se aplica despues de calcular."
    )
