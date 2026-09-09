"""Vista de jugadores: buscador y perfil de percentiles."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from futbol_front import charts, presentation
from futbol_front.client import ApiError
from futbol_front.state import (
    cached_catalog,
    cached_market,
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
        st.warning(
            "No hay datos cargados todavia. Lanza el ETL: "
            "`docker compose --profile etl run --rm etl`"
        )
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
    rival = _selector_de_comparacion(jugadores, seleccionado)

    try:
        perfil = cached_profile(
            player=seleccionado["player"],
            season=seleccionado["season"],
            team=seleccionado["team"],
            basis=base,
            population=poblacion,
        )
        # El segundo perfil se pide con la MISMA temporada, base y poblacion:
        # comparar percentiles calculados sobre poblaciones distintas no
        # significaria nada.
        perfil_rival = (
            cached_profile(
                player=rival["player"],
                season=rival["season"],
                team=rival["team"],
                basis=base,
                population=poblacion,
            )
            if rival
            else None
        )
    except ApiError as error:
        st.error(str(error))
        return

    plantillas = cached_templates()
    if perfil_rival:
        _comparacion(perfil, perfil_rival, plantillas)
        return

    rendimiento, mercado = st.tabs(["Rendimiento", "Mercado y carrera"])
    with rendimiento:
        _perfil(perfil, cliente_templates=plantillas)
    with mercado:
        _mercado(perfil["player"])


def _mercado(ficha: dict) -> None:
    """Ficha, valor de mercado y carrera del jugador, segun Transfermarkt.

    Va en su propia pestana y no junto al grafico porque responde a otra
    pregunta. El pizza chart dice como juega; esto dice quien es: que edad
    tiene, cuanto vale, de donde viene y hasta cuando esta atado. Un percentil
    95 no significa lo mismo a los 19 anos que a los 33, y sin esta pestana esa
    diferencia no se ve en ningun sitio.
    """
    try:
        datos = cached_market(ficha["player"], ficha["season"], ficha["team"])
    except ApiError as error:
        st.error(str(error))
        return

    for aviso in datos["caveats"]:
        st.warning(aviso, icon=":material/info:")

    tarjeta = datos["card"]
    if tarjeta:
        columnas = st.columns(4)
        columnas[0].metric("Edad", tarjeta["age"] if tarjeta["age"] is not None else "-")
        columnas[1].metric("Posicion", tarjeta["position"] or "-")
        columnas[2].metric("Pie", (tarjeta["foot"] or "-").capitalize())
        columnas[3].metric("Contrato", tarjeta["contract_until"] or "-")
        procedencia = tarjeta.get("signed_from")
        if procedencia:
            st.caption(f"Llego de {procedencia} el {tarjeta.get('joined_on') or 'sin fecha'}.")

    actual, maximo = datos["current_value_eur"], datos["peak_value_eur"]
    if actual is not None:
        columnas = st.columns(2)
        columnas[0].metric("Valor actual", _millones(actual))
        columnas[1].metric(
            "Maximo historico",
            _millones(maximo),
            delta=_millones(actual - maximo) if maximo and actual != maximo else None,
        )

    tasaciones = datos["valuations"]
    if tasaciones:
        st.subheader("Curva de valor")
        # La curva dice mas que la cifra: distingue al canterano en subida del
        # veterano en caida, aunque hoy valgan lo mismo.
        st.line_chart(
            {"Millones de euros": [(v["market_value_eur"] or 0) / 1e6 for v in tasaciones]},
            x_label="Tasaciones, de la mas antigua a la mas reciente",
        )

    fichajes = datos["transfers"]
    if fichajes:
        st.subheader("Carrera")
        st.dataframe(
            [
                {
                    "Fecha": f["transfer_date"],
                    "Desde": f["club_from"],
                    "Hasta": f["club_to"],
                    "Tipo": f["transfer_type"] or "sin constar",
                    "Importe": _millones(f["fee_eur"]),
                }
                for f in reversed(fichajes)
            ],
            hide_index=True,
            width="stretch",
        )
    elif not datos["caveats"]:
        st.caption("Sin fichajes registrados: puede llevar toda su carrera en el mismo club.")


def _millones(valor: float | None) -> str:
    """Un importe en millones, que es como se habla de esto en futbol."""
    if valor is None:
        return "-"
    return f"{valor / 1e6:,.1f} M EUR".replace(",", ".")


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


def _selector_de_comparacion(jugadores: list[dict], elegido: dict) -> dict | None:
    """Segundo jugador, opcional.

    Solo se ofrecen jugadores del mismo grupo de posicion: comparar a un central
    con un delantero sobre los ejes de un central no dice nada de ninguno de los
    dos.
    """
    comparables = [
        j
        for j in jugadores
        if j["position_group"] == elegido["position_group"]
        and (j["player"], j["team"]) != (elegido["player"], elegido["team"])
    ]
    if not comparables:
        return None

    etiquetas = {"Ninguno": None}
    etiquetas.update({f"{j['player']} - {j['team']}": j for j in comparables})
    seleccion = st.selectbox(
        "Comparar con",
        list(etiquetas),
        help="Solo jugadores de la misma posicion: los ejes del grafico dependen de ella.",
    )
    return etiquetas[seleccion]


def _comparacion(perfil: dict, rival: dict, templates: list[dict]) -> None:
    """Pinta a los dos jugadores sobre los mismos ejes."""
    ficha, ficha_rival = perfil["player"], rival["player"]
    plantilla = _plantilla(templates, ficha["position_group"])
    if not plantilla:
        st.info("Esta posicion no tiene grafico definido.")
        return

    for aviso in perfil["caveats"]:
        st.warning(aviso, icon=":material/info:")

    datos = presentation.prepare_comparison(perfil, rival, plantilla)
    if not len(datos):
        st.info("Los dos jugadores no comparten metricas con percentil.")
        return

    figura = charts.compare(
        datos,
        f"{ficha['player']} ({ficha['team']})",
        f"{ficha_rival['player']} ({ficha_rival['team']})",
        _subtitulo(perfil),
    )
    st.pyplot(figura, width="content")
    _descargar_figura(
        figura,
        presentation.chart_filename(ficha["player"], "vs", ficha_rival["player"], ficha["season"]),
    )
    if datos.missing:
        st.caption("Sin datos para: " + ", ".join(datos.missing))


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


# Como se pinta cada tipo de aviso. El rasgo va en gris a proposito: describe al
# jugador, no lo califica, y en verde se leeria como un elogio.
_ESTILO_AVISO = {
    "fortaleza": (st.success, ":material/trending_up:", "Muy por encima"),
    "debilidad": (st.error, ":material/trending_down:", "Muy por debajo"),
    "rasgo": (st.info, ":material/insights:", "Rasgo marcado"),
}


def _extremos(perfil: dict) -> None:
    """Senala las metricas en las que el jugador se sale de lo normal.

    El pizza chart ensena doce ejes a la vez y no dice por donde empezar a
    mirar. Esto contesta lo primero que se pregunta un analista delante de un
    perfil: que tiene este jugador de verdaderamente distinto.
    """
    avisos = presentation.extreme_metrics(perfil)
    if not avisos:
        st.caption(
            "Ninguna metrica se sale del rango habitual: es un perfil regular, "
            "sin un punto fuerte ni un agujero claros."
        )
        return

    with st.expander(f"Donde se sale de lo normal ({len(avisos)})", expanded=True):
        for aviso in avisos:
            pintar, icono, encabezado = _ESTILO_AVISO[aviso.kind]
            pintar(f"**{encabezado}** - {aviso.text}", icon=icono)
            if aviso.note:
                st.caption(f"Ojo: {aviso.note}.")


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
            figura = charts.pizza(datos, titulo, subtitulo)
            st.pyplot(figura, width="content")
            st.markdown(f"**{presentation.summarise_profile(perfil)}**")
            _descargar(figura, ficha["player"], ficha["season"], perfil["basis"])
            _extremos(perfil)
            if datos.missing:
                st.caption("Sin datos para: " + ", ".join(datos.missing))
        else:
            st.info("El jugador no tiene percentiles calculables en esta base.")

    _tabla(perfil)


def _descargar(figura, jugador: str, temporada: str, base: str) -> None:
    """Boton para llevarse el grafico.

    Sin esto, publicar un hallazgo obliga a hacer captura de pantalla. Es la
    diferencia entre una herramienta de consulta y una de la que sale contenido,
    que es uno de los propositos declarados del proyecto.
    """
    _descargar_figura(figura, presentation.chart_filename(jugador, temporada, base))


def _descargar_figura(figura, nombre: str) -> None:
    st.download_button(
        "Descargar grafico (PNG)",
        data=charts.to_png(figura),
        file_name=nombre,
        mime="image/png",
        icon=":material/download:",
        key=nombre,
    )


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
            width="stretch",
        )
