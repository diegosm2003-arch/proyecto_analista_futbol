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

from futbol_front import branding, enlaces
from futbol_front.client import ApiError
from futbol_front.state import cached_health
from futbol_front.views import chat, home, players, scouting, teams

st.set_page_config(
    page_title="Fútbol Analytics",
    page_icon=":soccer:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

VISTAS = {
    home.JUGADORES: ("Jugadores", players.render),
    home.EQUIPOS: ("Equipos", teams.render),
    home.SCOUTING: ("Scouting", scouting.render),
    home.CHAT: ("Asistente", chat.render),
}


def _cabecera(destino: str) -> None:
    """Barra superior: marca clicable y cambio de ambito.

    Va arriba y no en la barra lateral porque es donde el usuario ya esta
    mirando: los filtros de la vista vienen justo debajo, y tener navegacion y
    filtros juntos evita el salto de vista a un lateral que el resto del tiempo
    esta vacio.

    **La vuelta a inicio es el logotipo**, arriba a la izquierda, que es donde
    todo el mundo la busca desde que existen los sitios web. Antes era un boton
    suelto a la derecha, en el sitio donde suelen estar las acciones destructivas
    y la configuracion.
    """
    logo, marca, ambito, compartir = st.columns([1, 4, 5, 2], vertical_alignment="center")

    with logo:
        st.markdown(
            f'<div class="marca-logo">{branding.logo_html()}</div>',
            unsafe_allow_html=True,
        )
    with marca:
        # Boton sin borde: tiene que leerse como la marca, no como un control.
        st.button(
            "Fútbol Analytics",
            type="tertiary",
            help="Volver a la portada",
            on_click=home.ir_a,
            args=(None,),
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

    with compartir:
        enlaces.boton_de_copiado()


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
            st.warning("Sin datos cargados todavía.")
        else:
            st.caption(f"Última carga correcta: {version[:16].replace('T', ' ')}")

        # La fecha de la ultima carga CORRECTA no dice si el ultimo intento
        # fallo. Con la carga programada esa diferencia importa: sin este aviso,
        # un ETL roto pasaria semanas sin que nadie se enterase.
        ultimo = estado.get("last_etl_status")
        if ultimo == "failed":
            st.error("La última carga del ETL fallo: los datos no están al día.")
        elif ultimo == "stale":
            st.warning("La última carga se quedo a medias.")
        elif ultimo == "running":
            st.info("Hay una carga en marcha.")

        st.divider()
        with st.expander("Como leer los percentiles"):
            st.markdown(
                """
                Un percentil dice **donde esta** un jugador respecto a sus
                comparables, no cuanto hace. El percentil 80 en pases clave
                significa que el 80 % de los de su posición en las Big 5 dan
                menos.

                - **No todo lo alto es bueno.** Los tiros o las tarjetas
                  describen como juega, no lo bueno que es. La plataforma los
                  marca como rasgo y no como fortaleza.
                - **El grupo DF mezcla centrales y laterales.** Para afinar,
                  compara por rol en lugar de por posición.
                - **La PPDA es aproximada:** se calcula sobre todo el campo y no
                  sobre el 60 % rival como la canónica.
                - **No hay ajuste por posesión.** Ese ajuste divide por el tiempo
                  *sin* balón, que es la corrección de una métrica defensiva, y
                  Understat no publica ninguna. Ofrecerlo sería un botón que no
                  hace nada.
                """
            )


# El orden importa: la URL se lee antes de decidir que pintar, para que un
# enlace compartido abra la pantalla correcta, y se escribe despues, cuando el
# estado ya refleja lo que el usuario acaba de hacer.
enlaces.leer_una_vez()

destino = home.destino_actual()
if destino not in VISTAS:
    home.render()
else:
    _cabecera(destino)
    VISTAS[destino][1]()

enlaces.escribir()
_estado_de_los_datos()
