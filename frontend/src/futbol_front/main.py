"""Interfaz Streamlit.

Consume la API; nunca lee PostgreSQL. Esa frontera es lo que permite que el
mismo analisis lo use la interfaz y, mas adelante, el chat.

**La navegacion va por estado y no por paginas de Streamlit.** Se entra por una
portada donde se elige ambito —jugadores o equipos— y desde ahi se trabaja con
los filtros arriba. Con paginas, cada salto reinicia la pantalla y se pierde el
contexto con el que se entro; con estado, volver a la portada y entrar en la otra
vista conserva la temporada y la liga que ya estaban elegidas.
"""

from __future__ import annotations

import streamlit as st

from futbol_front.client import ApiError
from futbol_front.state import cached_health
from futbol_front.views import home, players, teams

st.set_page_config(
    page_title="Futbol Analytics",
    page_icon=":soccer:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

VISTAS = {
    home.JUGADORES: ("Jugadores", players.render),
    home.EQUIPOS: ("Equipos", teams.render),
}


def _cabecera(destino: str) -> None:
    """Barra superior: marca, cambio de ambito y vuelta a la portada.

    Va arriba y no en la barra lateral porque es donde el usuario ya esta
    mirando: los filtros de la vista vienen justo debajo, y tener navegacion y
    filtros juntos evita el salto de vista a un lateral que el resto del tiempo
    esta vacio.
    """
    marca, ambito, ayuda = st.columns([4, 3, 1], vertical_alignment="center")

    with marca:
        st.markdown(
            '<div style="font-weight:800;font-size:1.3rem;letter-spacing:-.02em;">'
            'Futbol <span style="color:var(--acento);">Analytics</span></div>',
            unsafe_allow_html=True,
        )

    with ambito:
        etiquetas = [nombre for nombre, _ in VISTAS.values()]
        claves = list(VISTAS)
        elegido = st.segmented_control(
            "Ambito",
            etiquetas,
            default=VISTAS[destino][0],
            label_visibility="collapsed",
            key="ambito",
        )
        if elegido and elegido != VISTAS[destino][0]:
            home.ir_a(claves[etiquetas.index(elegido)])
            st.rerun()

    with ayuda:
        st.button("Inicio", width="stretch", on_click=home.ir_a, args=(None,))


def _estado_de_los_datos() -> None:
    """Muestra en la barra lateral de que carga vienen los datos.

    No es un detalle tecnico: si el ETL fallo anoche, la interfaz sigue sirviendo
    los datos de la semana pasada sin que nada lo indique. Saber la fecha de la
    ultima carga evita sacar conclusiones sobre una jornada que no esta cargada.
    """
    with st.sidebar:
        st.subheader("Estado de los datos")
        try:
            estado = cached_health()
        except ApiError as error:
            st.error(f"API no disponible: {error}")
            return

        version = estado.get("data_version", "desconocida")
        if version in {"sin-datos", "desconocida"}:
            st.warning("Sin datos cargados todavia.")
        else:
            st.caption(f"Ultima carga correcta: {version[:16].replace('T', ' ')}")

        # La fecha de la ultima carga CORRECTA no dice si el ultimo intento
        # fallo. Con la carga programada esa diferencia importa: sin este aviso,
        # un ETL roto pasaria semanas sin que nadie se enterase.
        ultimo = estado.get("last_etl_status")
        if ultimo == "failed":
            st.error("La ultima carga del ETL fallo: los datos no estan al dia.")
        elif ultimo == "stale":
            st.warning("La ultima carga se quedo a medias.")
        elif ultimo == "running":
            st.info("Hay una carga en marcha.")

        st.divider()
        with st.expander("Como leer los percentiles"):
            st.markdown(
                """
                Un percentil dice **donde esta** un jugador respecto a sus
                comparables, no cuanto hace. El percentil 80 en pases clave
                significa que el 80 % de los de su posicion en las Big 5 dan
                menos.

                - **No todo lo alto es bueno.** Los tiros o las tarjetas
                  describen como juega, no lo bueno que es. La plataforma los
                  marca como rasgo y no como fortaleza.
                - **El grupo DF mezcla centrales y laterales.** Para afinar,
                  compara por rol en lugar de por posicion.
                - **La PPDA es aproximada:** se calcula sobre todo el campo y no
                  sobre el 60 % rival como la canonica.
                """
            )


destino = home.destino_actual()
if destino not in VISTAS:
    home.render()
else:
    _cabecera(destino)
    VISTAS[destino][1]()
_estado_de_los_datos()
