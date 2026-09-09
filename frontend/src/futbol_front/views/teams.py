"""Vista de equipos: mapa de estilos de juego."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from futbol_front import charts, presentation
from futbol_front.client import ApiError
from futbol_front.state import cached_catalog, cached_styles

# Por debajo de este valor la particion es debil. No invalida el analisis: los
# estilos de juego forman un continuo y no grupos separados.
WEAK_SILHOUETTE = 0.25


def render() -> None:
    st.title("Estilo de juego")
    st.caption(
        "Los equipos se agrupan por como juegan, no por lo bien que juegan. "
        "El clustering usa todas las ligas cargadas y el filtro se aplica despues."
    )

    try:
        catalogo = cached_catalog()
    except ApiError as error:
        st.error(f"No se ha podido leer el catalogo: {error}")
        return

    if not catalogo["seasons"]:
        st.warning(
            "No hay datos cargados todavia. Lanza el ETL: "
            "`docker compose --profile etl run --rm etl`"
        )
        return

    temporada, liga, n_estilos = _filtros(catalogo)

    try:
        informe = cached_styles(season=temporada, league=liga, n_styles=n_estilos)
    except ApiError as error:
        st.error(str(error))
        return

    if not informe["teams"]:
        st.info("No hay equipos que mostrar con estos filtros.")
        return

    _calidad(informe)
    _mapa(informe, temporada)
    _tabla(informe)


def _filtros(catalogo: dict) -> tuple[str, str | None, int]:
    with st.sidebar:
        st.header("Filtros")
        temporada = st.selectbox(
            "Temporada", catalogo["seasons"], index=len(catalogo["seasons"]) - 1
        )
        liga = st.selectbox("Liga", ["Todas las Big 5", *catalogo["leagues"]])
        n_estilos = st.slider("Numero de estilos", min_value=2, max_value=10, value=5)
        st.caption(
            "Los estilos no estan definidos de antemano: cada grupo se describe "
            "por sus dos rasgos mas extremos."
        )
    return temporada, (None if liga == "Todas las Big 5" else liga), n_estilos


def _calidad(informe: dict) -> None:
    silueta = informe.get("silhouette")
    if silueta is None:
        return
    if silueta < WEAK_SILHOUETTE:
        st.info(
            f"Separacion debil entre estilos (silhouette {silueta:.2f}). No es un "
            "error: los estilos de juego son un continuo y no grupos nitidos. "
            "Prueba con menos estilos.",
            icon=":material/info:",
        )


def _mapa(informe: dict, temporada: str) -> None:
    datos = presentation.prepare_style_map(informe)
    if not len(datos):
        st.info("Ningun equipo tiene posesion y presion calculables.")
        return

    figura = charts.style_map(datos, f"Estilos de juego - {temporada}")
    st.pyplot(figura)
    st.download_button(
        "Descargar mapa (PNG)",
        data=charts.to_png(figura),
        file_name=presentation.chart_filename("estilos", temporada),
        mime="image/png",
        icon=":material/download:",
    )
    st.caption(
        "La PPDA es aproximada: se calcula sobre todo el campo porque FBref no "
        "publica el pase del rival por zonas. Ordena bien a los equipos, pero no "
        "es comparable con la PPDA de otras fuentes."
    )


def _tabla(informe: dict) -> None:
    filas = pd.DataFrame(informe["teams"])
    if filas.empty:
        return

    filas = filas.rename(
        columns={
            "team": "Equipo",
            "league": "Liga",
            "style": "Estilo",
            "possession": "Posesion (%)",
            "ppda": "PPDA aprox.",
            "pressing_height": "Entradas en campo rival",
        }
    )
    columnas = [
        columna
        for columna in (
            "Equipo",
            "Liga",
            "Estilo",
            "Posesion (%)",
            "PPDA aprox.",
            "Entradas en campo rival",
        )
        if columna in filas
    ]

    st.dataframe(
        filas[columnas].sort_values("Estilo").round(2),
        hide_index=True,
        width="stretch",
    )
