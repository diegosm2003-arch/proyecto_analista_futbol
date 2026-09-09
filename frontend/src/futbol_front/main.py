"""Interfaz Streamlit.

Consume la API; nunca lee PostgreSQL. Esa frontera es lo que permite que el
mismo analisis lo use la interfaz y, mas adelante, el chat.
"""

from __future__ import annotations

import streamlit as st

from futbol_front.client import ApiError
from futbol_front.state import cached_health
from futbol_front.views import players, teams

st.set_page_config(
    page_title="Futbol Analytics",
    page_icon=":soccer:",
    layout="wide",
)


def _estado_de_los_datos() -> None:
    """Muestra en la barra lateral de que carga vienen los datos.

    No es un detalle tecnico: si el ETL fallo anoche, la interfaz sigue sirviendo
    los datos de la semana pasada sin que nada lo indique. Saber la fecha de la
    ultima carga evita sacar conclusiones sobre una jornada que no esta cargada.
    """
    with st.sidebar:
        st.divider()
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


def _acerca_de() -> None:
    st.title("Sobre esta plataforma")
    st.markdown(
        """
        Analitica de **LaLiga** con las **Big 5 ligas europeas** como poblacion
        de referencia.

        ### Como leer los percentiles

        Un percentil dice donde esta un jugador respecto a sus comparables, no
        cuanto hace. El percentil 80 en pases progresivos significa que el 80 %
        de los jugadores de su posicion en las Big 5 progresan menos que el.

        La poblacion son **las cinco grandes ligas y no solo LaLiga**: con una
        sola liga la muestra por posicion se queda corta y el percentil acaba
        midiendo el ruido muestral. El filtro por liga se aplica despues de
        calcular.

        ### Tres advertencias

        - **No todas las metricas son buenas o malas.** Los despejes o las
          entradas por tercio describen donde defiende un equipo, no la calidad
          del jugador. La plataforma no las pinta como virtud.
        - **El grupo DF mezcla centrales y laterales.** FBref no publica la
          posicion detallada, asi que el rol lo asigna un clustering sobre el
          reparto de toques por zona del campo. Para una comparacion mas fina,
          usa la opcion de comparar por rol.
        - **La PPDA es aproximada.** Se calcula sobre todo el campo, no sobre el
          60 % rival como la canonica, porque FBref no publica el pase del
          rival por zonas.
        """
    )


# La ruta de cada pagina se escribe a mano. Streamlit la deduce del nombre del
# callable cuando no se le da, y las dos vistas exportan una funcion `render`:
# dos paginas con la misma ruta, y la aplicacion no arranca. Escribirla ademas
# fija la URL, que si se dedujera cambiaria al renombrar una funcion.
paginas = [
    st.Page(
        players.render,
        title="Jugadores",
        icon=":material/person:",
        url_path="jugadores",
        default=True,
    ),
    st.Page(
        teams.render,
        title="Estilo de equipo",
        icon=":material/groups:",
        url_path="equipos",
    ),
    st.Page(_acerca_de, title="Como leerlo", icon=":material/help:", url_path="ayuda"),
]

# La navegacion se ejecuta primero para que los filtros de cada vista queden
# arriba en la barra lateral y el estado de los datos debajo, tras el divisor.
st.navigation(paginas).run()
_estado_de_los_datos()
