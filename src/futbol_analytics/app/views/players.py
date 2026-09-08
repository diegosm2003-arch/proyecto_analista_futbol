"""Vista de jugadores: buscador y perfil de percentiles."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from futbol_analytics.app import charts, presentation
from futbol_analytics.app.client import ApiError
from futbol_analytics.app.state import (
    cached_catalog,
    cached_profile,
    cached_search,
    cached_templates,
)

BASES = {
    "Por 90 minutos": "per90",
    "Ajustado por posesion": "padj",
}

POBLACIONES = {
    "Su posicion (DF, MF, FW)": "position",
    "Su rol (mas fino, muestra menor)": "role",
}


def render() -> None:
    st.title("Percentiles por posicion")
    st.caption(
        "Cada eje es el percentil del jugador frente a los jugadores comparables "
        "de las Big 5 ligas en esa temporada, no un valor absoluto."
    )

    try:
        catalogo = cached_catalog()
    except ApiError as error:
        st.error(f"No se ha podido leer el catalogo: {error}")
        return

    if not catalogo["seasons"]:
        st.warning("No hay datos cargados. Ejecuta el ETL en el equipo personal.")
        return

    filtros = _filtros(catalogo)
    try:
        jugadores = cached_search(**filtros)
    except ApiError as error:
        st.error(str(error))
        return

    if not jugadores:
        st.info("Ningun jugador cumple los filtros.")
        return

    seleccionado = _selector(jugadores)
    base, poblacion = _opciones_de_comparacion()

    try:
        perfil = cached_profile(
            player=seleccionado["player"],
            season=seleccionado["season"],
            team=seleccionado["team"],
            basis=base,
            population=poblacion,
        )
    except ApiError as error:
        st.error(str(error))
        return

    _perfil(perfil, cliente_templates=cached_templates())


def _filtros(catalogo: dict) -> dict:
    """Barra lateral de filtros. Devuelve los parametros de busqueda."""
    with st.sidebar:
        st.header("Filtros")
        temporada = st.selectbox(
            "Temporada", catalogo["seasons"], index=len(catalogo["seasons"]) - 1
        )
        liga = st.selectbox("Liga", ["Todas las Big 5", *catalogo["leagues"]])
        posicion = st.selectbox("Posicion", ["Todas", "GK", "DF", "MF", "FW"])
        nombre = st.text_input("Nombre", placeholder="Busqueda parcial")
        st.caption(
            f"Solo entran en la comparacion los jugadores con al menos "
            f"{catalogo['min_minutes']} minutos."
        )

    return {
        "season": temporada,
        "league": None if liga == "Todas las Big 5" else liga,
        "position_group": None if posicion == "Todas" else posicion,
        "name": nombre or None,
    }


def _selector(jugadores: list[dict]) -> dict:
    """Selector de jugador. Distingue etapas si hubo traspaso."""
    etiquetas = {f"{j['player']} - {j['team']} ({j['minutes']} min)": j for j in jugadores}
    elegido = st.selectbox(f"Jugador ({len(jugadores)} encontrados)", list(etiquetas))
    return etiquetas[elegido]


def _opciones_de_comparacion() -> tuple[str, str]:
    columna_base, columna_poblacion = st.columns(2)
    with columna_base:
        base = st.radio(
            "Normalizacion",
            list(BASES),
            horizontal=True,
            help=(
                "El ajuste por posesion corrige que un jugador de un equipo que "
                "domina tiene menos ocasiones de defender."
            ),
        )
    with columna_poblacion:
        poblacion = st.radio(
            "Comparar contra",
            list(POBLACIONES),
            horizontal=True,
            help="El rol es mas preciso, pero la poblacion se reduce a un cuarto.",
        )
    return BASES[base], POBLACIONES[poblacion]


def _perfil(perfil: dict, cliente_templates: list[dict]) -> None:
    """Pinta el grafico, las advertencias y la tabla de metricas."""
    ficha = perfil["player"]
    plantilla = _plantilla(cliente_templates, ficha["position_group"])

    for aviso in perfil["caveats"]:
        st.warning(aviso, icon=":material/info:")

    if not plantilla:
        st.info(
            "No hay grafico definido para esta posicion. Las metricas de portero "
            "disponibles en FBref no dan para un pizza chart legible, asi que se "
            "muestra la tabla."
        )
    else:
        datos = presentation.prepare_pizza(perfil, plantilla)
        if len(datos):
            titulo = f"{ficha['player']} - {ficha['team']}"
            subtitulo = _subtitulo(perfil)
            st.pyplot(charts.pizza(datos, titulo, subtitulo), use_container_width=False)
            st.markdown(f"**{presentation.summarise_profile(perfil)}**")
            if datos.missing:
                st.caption("Sin datos para: " + ", ".join(datos.missing))
        else:
            st.info("El jugador no tiene percentiles calculables en esta base.")

    _tabla(perfil)


def _plantilla(templates: list[dict], position_group: str | None) -> list[dict]:
    for plantilla in templates:
        if plantilla["position_group"] == position_group:
            return plantilla["slices"]
    return []


def _subtitulo(perfil: dict) -> str:
    ficha = perfil["player"]
    rol = ficha["detailed_position"] or ficha["position_group"] or "sin posicion"
    base = "por 90 min" if perfil["basis"] == "per90" else "ajustado por posesion"
    return (
        f"{rol} | {ficha['season']} | {base} | "
        f"percentil frente a {perfil['population_size']} jugadores"
    )


def _tabla(perfil: dict) -> None:
    """Tabla con el detalle numerico, para quien quiera el valor y no el percentil."""
    filas = pd.DataFrame(perfil["metrics"])
    if filas.empty:
        return

    filas = filas.rename(
        columns={
            "label": "Metrica",
            "total": "Total",
            "per90": "Por 90",
            "padj": "Ajustado",
            "percentile": "Percentil",
        }
    )
    columnas = [c for c in ("Metrica", "Total", "Por 90", "Ajustado", "Percentil") if c in filas]

    with st.expander("Detalle numerico"):
        st.caption(
            "Las metricas sin direccion (estilo, como despejes) tienen percentil "
            "pero no significan mejor ni peor: describen donde juega."
        )
        st.dataframe(
            filas[columnas].round(2),
            hide_index=True,
            use_container_width=True,
        )
