"""Vista de equipos: mapa de estilos de juego.

Los filtros van arriba, igual que en la vista de jugadores: son lo que define lo
que se esta mirando y se cambian constantemente, asi que van en la misma linea
de vision que el resultado.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from futbol_front import charts, presentation
from futbol_front.client import ApiError
from futbol_front.state import cached_catalog, cached_conceded, cached_styles
from futbol_front.theme import Palette, apply
from futbol_front.views import browse

# Por debajo de este valor la particion es debil. No invalida el analisis: los
# estilos de juego forman un continuo y no grupos separados.
WEAK_SILHOUETTE = 0.25


def render() -> None:
    try:
        catalogo = cached_catalog()
    except ApiError as error:
        apply(None)
        st.error(f"No se ha podido leer el catalogo: {error}")
        return

    if not catalogo["seasons"]:
        apply(None)
        st.warning(
            "No hay datos cargados todavía. Lanza el ETL: "
            "`docker compose --profile etl run --rm etl`"
        )
        return

    liga = browse.liga_actual()
    paleta = apply(liga)
    browse.migas(paleta)

    if liga is None:
        browse.selector_de_liga(catalogo["leagues"], "Elige una liga")
        st.divider()
        st.caption(
            "También puedes ver las cinco a la vez: el clustering se calcula siempre "
            "sobre todas y la liga solo filtra a quien se pinta."
        )
        st.button(
            "Ver las cinco grandes juntas",
            on_click=browse.elegir_liga,
            args=(TODAS,),
        )
        return

    temporada, n_estilos = _filtros(catalogo)
    liga_filtro = None if liga == TODAS else liga

    try:
        informe = cached_styles(season=temporada, league=liga_filtro, n_styles=n_estilos)
    except ApiError as error:
        st.error(str(error))
        return

    if not informe["teams"]:
        st.info("No hay equipos que mostrar con estos filtros.")
        return

    estilos, concedidos = st.tabs(["Estilo de juego", "Qué le rematan"])
    with concedidos:
        _concedidos(informe, temporada, paleta)
    with estilos:
        _pestana_de_estilos(informe, temporada, paleta)


def _pestana_de_estilos(informe: dict, temporada: str, paleta) -> None:
    mapa, panel = st.columns([3, 2], gap="large")
    with mapa:
        _mapa(informe, temporada, paleta)
    with panel:
        _panel(informe)

    _tabla(informe)


# Valor que representa "las cinco a la vez" dentro de la navegacion por liga.
TODAS = "__todas__"


def _concedidos(informe: dict, temporada: str, paleta) -> None:
    """Desde dónde le rematan a un equipo.

    Es lo más cerca que se puede estar de medir defensa con esta fuente. No hay
    entradas ni intercepciones, pero sí el resultado de defender: cuántos
    remates permite un equipo, desde dónde y de qué calidad.

    La distinción futbolística que esto permite y el total de goles encajados
    esconde: un bloque bajo que concede muchos disparos lejanos y un bloque alto
    que concede pocos pero claros son estilos opuestos que pueden acabar la
    jornada con los mismos goles en contra.
    """
    equipos = sorted({e["team"] for e in informe["teams"]})
    if not equipos:
        st.info("No hay equipos cargados.")
        return

    equipo = st.selectbox("Equipo", equipos, key="equipo_concedidos")

    try:
        datos = cached_conceded(equipo, temporada)
    except ApiError as error:
        st.error(str(error))
        return

    if not datos["shots"]:
        st.info("Sin tiros cargados para este equipo. Lanza el ETL con `--only shots`.")
        return

    campo, panel = st.columns([2, 3], gap="large")

    with campo:
        figura = charts.shot_map(
            datos["shots"],
            f"Le rematan a {equipo}",
            paleta,
            conceded=True,
        )
        st.pyplot(figura, width="content")

    with panel:
        columnas = st.columns(3)
        columnas[0].metric("Remates recibidos", len(datos["shots"]))
        columnas[1].metric("Goles encajados", datos["goals_conceded"])
        columnas[2].metric(
            "xG por remate",
            f"{datos['xg_per_shot']:.3f}" if datos["xg_per_shot"] else "-",
        )

        partidos = max(datos["matches"], 1)
        st.markdown(
            '<div class="panel-detalle">'
            '<div class="titulo">Por partido</div>'
            f'<div class="valor">{len(datos["shots"]) / partidos:.1f} remates · '
            f"{datos['xg_conceded'] / partidos:.2f} de xG en contra</div></div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"Sobre {datos['matches']} partidos con tiros cargados. La calidad media de "
            "lo que concede dice más que el total: conceder veinte disparos lejanos no "
            "es lo mismo que conceder cinco claros."
        )

        for aviso in datos["caveats"]:
            st.caption(f":orange[{aviso}]")


def _filtros(catalogo: dict) -> tuple[str, int]:
    """Cinta de filtros en la parte superior.

    La liga ya la ha decidido la navegacion, asi que aqui solo quedan la
    temporada y cuantos estilos se piden.
    """
    # Contenedor de verdad, no un <div> de markdown: Streamlit lo cierra en
    # cuanto acaba el markdown y los widgets se quedaban fuera.
    with st.container(border=True):
        temporada_c, estilos_c = st.columns([1, 3])
        with temporada_c:
            temporada = st.selectbox(
                "Temporada",
                catalogo["seasons"],
                index=len(catalogo["seasons"]) - 1,
                format_func=presentation.season_label,
            )
        with estilos_c:
            n_estilos = st.slider("Número de estilos", min_value=2, max_value=16, value=6)
        st.caption(
            "Los equipos se agrupan por como juegan, no por lo bien que juegan. Los estilos "
            "no están definidos de antemano: cada grupo se describe por sus rasgos más "
            "extremos. El clustering usa todas las ligas y el filtro se aplica después."
        )
    return temporada, n_estilos


def _panel(informe: dict) -> None:
    """Lectura del mapa, al lado del mapa.

    Los estilos y sus advertencias se leen A LA VEZ que el grafico: enterarse de
    que la particion es debil despues de haber interpretado los grupos llega
    tarde, la conclusion ya esta sacada.
    """
    _calidad(informe)

    por_estilo: dict[str, list[str]] = {}
    for equipo in informe["teams"]:
        por_estilo.setdefault(equipo["style"], []).append(equipo["team"])

    st.markdown("###### Estilos encontrados")
    for estilo, nombres in sorted(por_estilo.items()):
        visibles = ", ".join(sorted(nombres)[:6])
        resto = " y otros" if len(nombres) > 6 else ""
        st.markdown(
            '<div class="panel-detalle">'
            f'<div class="título">{estilo} &middot; {len(nombres)} equipos</div>'
            f'<div class="valor">{visibles}{resto}</div></div>',
            unsafe_allow_html=True,
        )

    with st.popover("Como leer el mapa", width="stretch"):
        st.markdown(
            "El eje vertical esta **invertido**: una PPDA baja significa presión alta, "
            "así que los equipos más agresivos quedan arriba."
        )
        st.markdown(
            "La **PPDA es aproximada**: se calcula sobre todo el campo porque la fuente "
            "no publica el pase del rival por zonas. Ordena bien a los equipos, pero no "
            "es comparable con la PPDA de otras fuentes."
        )


def _calidad(informe: dict) -> None:
    silueta = informe.get("silhouette")
    if silueta is None:
        return
    if silueta < WEAK_SILHOUETTE:
        st.info(
            f"Separación debil entre estilos (silhouette {silueta:.2f}). No es un "
            "error: los estilos de juego son un continuo y no grupos nitidos. "
            "Prueba con menos estilos.",
            icon=":material/info:",
        )


def _mapa(informe: dict, temporada: str, paleta: Palette) -> None:
    datos = presentation.prepare_style_map(informe)
    if not len(datos):
        st.info("Ningun equipo tiene territorio y presión calculables.")
        return

    figura = charts.style_map(
        datos, f"Estilos de juego - {presentation.season_label(temporada)}", paleta
    )
    st.pyplot(figura, width="content")
    st.download_button(
        "Descargar mapa (PNG)",
        data=charts.to_png(figura),
        file_name=presentation.chart_filename("estilos", temporada),
        mime="image/png",
        icon=":material/download:",
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
            "territory": "Llegadas por partido",
            "ppda": "PPDA aprox.",
            "chance_creation": "npxG por partido",
            "chance_prevention": "npxG concedido",
        }
    )
    columnas = [
        columna
        for columna in (
            "Equipo",
            "Liga",
            "Estilo",
            "Llegadas por partido",
            "PPDA aprox.",
            "npxG por partido",
            "npxG concedido",
        )
        if columna in filas
    ]

    st.dataframe(
        filas[columnas].sort_values("Estilo").round(2),
        hide_index=True,
        width="stretch",
    )
