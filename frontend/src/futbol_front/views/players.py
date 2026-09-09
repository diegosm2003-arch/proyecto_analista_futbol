"""Vista de jugadores: buscador, perfil de percentiles y comparables.

**Los filtros van arriba y no en un lateral.** Se cambian constantemente y son
lo que define lo que se esta mirando; tenerlos en la misma linea de vision que
el resultado evita el salto de ojo a un lateral que el resto del tiempo esta
vacio, y deja la barra lateral para lo que se consulta de vez en cuando: de que
carga vienen los datos.

**El grafico y su lectura van uno al lado del otro.** El pizza chart ensena doce
ejes a la vez y no dice por donde empezar; el panel de la derecha responde a eso
sin obligar a bajar. Por eso el grafico se dibuja mas pequeno que antes: cabian
los dos, pero solo si el circulo no ocupa la pantalla entera.

**Los comparables cierran la pantalla.** Es la pregunta con la que sigue un
scout despues de ver un perfil que le gusta: quien mas juega asi.
"""

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
    cached_similar,
    cached_squad,
    cached_teams,
    cached_templates,
)
from futbol_front.theme import Palette, apply
from futbol_front.views import browse

BASES = {
    "Por 90 minutos": "per90",
    "Ajustado por posesion": "padj",
}

POBLACIONES = {
    "Su posicion (DF, MF, FW)": "position",
    "Su rol (mas fino, muestra menor)": "role",
}

TODAS_LAS_LIGAS = "Todas las Big 5"

# Comparables que se piden. Seis caben en el grafico sin que las etiquetas se
# pisen, y son suficientes para ver un patron.
COMPARABLES = 6


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
            "No hay datos cargados todavia. Lanza el ETL: "
            "`docker compose --profile etl run --rm etl`"
        )
        return

    temporada = _temporada(catalogo)
    liga = browse.liga_actual()
    # El tema se aplica en cuanto se sabe la liga: el acento acompana a la
    # navegacion desde el primer paso, no solo dentro del analisis.
    paleta = apply(liga)
    browse.migas(paleta)

    # Paso 1: la liga.
    if liga is None:
        browse.selector_de_liga(catalogo["leagues"], "Elige una liga")
        return

    # Paso 2: el equipo.
    equipo = browse.equipo_actual()
    if equipo is None:
        try:
            equipos = cached_teams(temporada, liga)
        except ApiError as error:
            st.error(str(error))
            return
        browse.selector_de_equipo(equipos, f"Equipos de {paleta.name}")
        return

    # Paso 3: la plantilla, ya con los filtros arriba.
    filtros, base, poblacion = _barra_de_filtros(catalogo, temporada, liga, equipo)

    try:
        jugadores = cached_search(**filtros)
    except ApiError as error:
        st.error(str(error))
        return

    if not jugadores:
        st.info("Ningun jugador del equipo cumple los filtros. Prueba a quitar el nombre.")
        return

    seleccionado, rival = _seleccion(jugadores, paleta)

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
        _comparacion(perfil, perfil_rival, plantillas, paleta)
        return

    rendimiento, mercado, plantel = st.tabs(["Rendimiento", "Mercado y carrera", "Plantilla"])
    with rendimiento:
        _perfil(perfil, plantillas, paleta)
        _similares(perfil, base, paleta)
    with mercado:
        _mercado(perfil["player"])
    with plantel:
        _plantel(temporada, liga, equipo, paleta)


# --- Filtros ----------------------------------------------------------------


def _temporada(catalogo: dict) -> str:
    """Temporada activa, elegida en la barra superior de la vista.

    Se lee aparte de los demas filtros porque hace falta ya en el primer paso de
    la navegacion, para saber que equipos hay cargados.
    """
    return st.session_state.get("temporada_activa") or catalogo["seasons"][-1]


def _barra_de_filtros(
    catalogo: dict, temporada: str, liga: str, equipo: str
) -> tuple[dict, str, str]:
    """Cinta de filtros en la parte superior.

    La liga y el equipo ya estan decididos por la navegacion, asi que aqui solo
    quedan los filtros que acotan dentro de la plantilla y las dos opciones que
    definen contra quien se compara.
    """
    # Un contenedor de verdad y no un <div> de markdown: Streamlit cierra el div
    # en cuanto termina el markdown, asi que los widgets quedaban fuera y lo que
    # se veia era una franja vacia encima de los filtros.
    with st.container(border=True):
        temporada_c, posicion_c, nombre_c = st.columns([1, 1, 2])
        with temporada_c:
            temporada = st.selectbox(
                "Temporada",
                catalogo["seasons"],
                index=catalogo["seasons"].index(temporada),
                key="temporada_activa",
            )
        with posicion_c:
            posicion = st.selectbox("Posicion", ["Todas", "GK", "DF", "MF", "FW"])
        with nombre_c:
            nombre = st.text_input("Nombre", placeholder="Busqueda parcial")

        base_c, poblacion_c = st.columns(2)
        with base_c:
            base = st.radio(
                "Normalizacion",
                list(BASES),
                horizontal=True,
                help=(
                    "El ajuste por posesion corrige que un jugador de un equipo que "
                    "domina tiene menos ocasiones de defender."
                ),
            )
        with poblacion_c:
            poblacion = st.radio(
                "Comparar contra",
                list(POBLACIONES),
                horizontal=True,
                help="El rol es mas preciso, pero la poblacion se reduce a un cuarto.",
            )

        _aviso_de_umbral(catalogo, temporada)

    return (
        {
            "season": temporada,
            "league": liga,
            "team": equipo,
            "position_group": None if posicion == "Todas" else posicion,
            "name": nombre or None,
        },
        BASES[base],
        POBLACIONES[poblacion],
    )


def _aviso_de_umbral(catalogo: dict, temporada: str) -> None:
    """El umbral real, no el configurado.

    Al principio de temporada baja para que la plataforma no salga vacia, y
    anunciar el otro seria mentir sobre quien esta entrando en la comparacion.
    """
    umbral = catalogo.get("min_minutes_applied", {}).get(temporada, catalogo["min_minutes"])
    if umbral < catalogo["min_minutes"]:
        st.caption(
            f":orange[Entran los jugadores con al menos **{umbral} minutos**. El umbral "
            f"ha bajado desde los {catalogo['min_minutes']} habituales porque la "
            f"temporada acaba de empezar: con tan pocos partidos, las metricas por 90 "
            f"son inestables.]"
        )
    else:
        st.caption(f"Entran en la comparacion los jugadores con al menos {umbral} minutos.")


def _seleccion(jugadores: list[dict], paleta: Palette) -> tuple[dict, dict | None]:
    """Jugador a analizar y, opcionalmente, con quien compararlo."""
    jugador_c, rival_c = st.columns([3, 2])

    with jugador_c:
        etiquetas = {f"{j['player']} - {j['team']} ({j['minutes']} min)": j for j in jugadores}
        elegido = etiquetas[
            st.selectbox(f"Jugador ({len(jugadores)} encontrados)", list(etiquetas))
        ]

    with rival_c:
        rival = _selector_de_comparacion(jugadores, elegido)

    ficha = elegido
    st.markdown(
        f'<div class="cinta-liga">{paleta.name}</div> '
        f'<span style="color:#8D9AB4;margin-left:.6rem;">{ficha["team"]} &middot; '
        f"{ficha['position_group'] or 'sin posicion'}"
        f"{' &middot; ' + ficha['detailed_position'] if ficha['detailed_position'] else ''}"
        f"</span>",
        unsafe_allow_html=True,
    )
    return elegido, rival


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

    etiquetas: dict[str, dict | None] = {"Ninguno": None}
    etiquetas.update({f"{j['player']} - {j['team']}": j for j in comparables})
    seleccion = st.selectbox(
        "Comparar con",
        list(etiquetas),
        help="Solo jugadores de la misma posicion: los ejes del grafico dependen de ella.",
    )
    return etiquetas[seleccion]


# --- Perfil -----------------------------------------------------------------


def _perfil(perfil: dict, plantillas: list[dict], paleta: Palette) -> None:
    """Grafico a la izquierda, lectura del grafico a la derecha."""
    ficha = perfil["player"]
    plantilla = _plantilla(plantillas, ficha["position_group"])

    if not plantilla:
        st.info(
            "No hay grafico definido para esta posicion. Understat no publica metricas "
            "de portero, asi que se muestra solo la tabla."
        )
        _tabla(perfil)
        return

    datos = presentation.prepare_pizza(perfil, plantilla)
    if not len(datos):
        st.info("El jugador no tiene percentiles calculables en esta base.")
        return

    grafico, panel = st.columns([3, 2], gap="large")

    with grafico:
        figura = charts.pizza(
            datos, f"{ficha['player']} - {ficha['team']}", _subtitulo(perfil), paleta
        )
        st.pyplot(figura, width="content")
        if datos.missing:
            st.caption("Sin datos para: " + ", ".join(datos.missing))
        _descargar(figura, ficha["player"], ficha["season"], perfil["basis"])

    with panel:
        _panel_de_lectura(perfil)


def _panel_de_lectura(perfil: dict) -> None:
    """Lo que hay que saber para leer el grafico que tiene al lado.

    Va aqui y no debajo porque se lee A LA VEZ que el grafico: bajar para saber
    que un percentil esta inflado por la posesion del equipo llega tarde, ya se
    ha sacado la conclusion.
    """
    st.markdown(f"**{presentation.summarise_profile(perfil)}**")

    avisos = presentation.extreme_metrics(perfil)
    if avisos:
        st.markdown("###### Donde se sale de lo normal")
        for aviso in avisos:
            pintar, icono, encabezado = _ESTILO_AVISO[aviso.kind]
            pintar(f"**{encabezado}** · {aviso.text}", icon=icono)
            if aviso.note:
                st.caption(f"Ojo: {aviso.note}.")
    else:
        st.caption(
            "Ninguna metrica se sale del rango habitual: es un perfil regular, sin un "
            "punto fuerte ni un agujero claros."
        )

    if perfil["caveats"]:
        with st.popover("Advertencias de lectura", width="stretch"):
            for aviso in perfil["caveats"]:
                st.warning(aviso, icon=":material/info:")

    with st.popover("Detalle numerico", width="stretch"):
        _detalle(perfil)


# Como se pinta cada tipo de aviso. El rasgo va en azul a proposito: describe al
# jugador, no lo califica, y en verde se leeria como un elogio.
_ESTILO_AVISO = {
    "fortaleza": (st.success, ":material/trending_up:", "Muy por encima"),
    "debilidad": (st.error, ":material/trending_down:", "Muy por debajo"),
    "rasgo": (st.info, ":material/insights:", "Rasgo marcado"),
}


# --- Comparables ------------------------------------------------------------


def _similares(perfil: dict, base: str, paleta: Palette) -> None:
    """Quien mas juega asi, con dos graficos que responden a cosas distintas.

    Las barras dicen *cuanto* se parecen; el plano dice *por donde*. Dos
    jugadores con el mismo porcentaje pueden estar uno arriba y otro a la
    derecha, y para un scout esa diferencia lo es todo.
    """
    ficha = perfil["player"]
    st.divider()
    st.subheader("Jugadores similares")

    try:
        datos = cached_similar(
            player=ficha["player"],
            season=ficha["season"],
            team=ficha["team"],
            basis=base,
            limit=COMPARABLES,
        )
    except ApiError as error:
        st.error(str(error))
        return

    vecinos = datos["neighbours"]
    if not vecinos:
        st.info(
            "Sin comparables. Suele pasar con perfiles a los que les faltan metricas, "
            "o en posiciones con pocos jugadores por encima del umbral de minutos."
        )
        return

    st.caption(
        f"Los mas parecidos a **{ficha['player']}** dentro de su grupo "
        f"({datos['population_group']}) en las Big 5, por su vector de percentiles."
    )

    barras_c, plano_c = st.columns(2, gap="large")

    with barras_c:
        figura = charts.similarity_bars(
            [f"{v['player']} ({v['team']})" for v in vecinos],
            [v["similarity"] for v in vecinos],
            paleta,
        )
        st.pyplot(figura, width="content")

    with plano_c:
        _plano(datos, ficha["player"], paleta)

    _tabla_de_similares(vecinos)

    for aviso in datos["caveats"]:
        st.caption(f":orange[{aviso}]")


def _plano(datos: dict, nombre: str, paleta: Palette) -> None:
    """Plano de dos familias, con los ejes que el usuario elija.

    Se dejan elegir porque la pregunta cambia con la posicion: en un delantero
    interesa finalizacion frente a creacion, y en un mediocentro construccion
    frente a creacion.
    """
    familias = sorted(datos["profile"])
    if len(familias) < 2:
        st.info("El perfil no tiene familias suficientes para dibujar el plano.")
        return

    eje_x, eje_y = st.columns(2)
    with eje_x:
        x = st.selectbox("Eje horizontal", familias, index=0, key="plano_x")
    with eje_y:
        y = st.selectbox("Eje vertical", familias, index=min(len(familias) - 1, 1), key="plano_y")

    vecinos = [
        (v["player"], v["profile"].get(x), v["profile"].get(y))
        for v in datos["neighbours"]
        if v["profile"].get(x) is not None and v["profile"].get(y) is not None
    ]
    figura = charts.scouting_plane(
        (nombre, datos["profile"][x], datos["profile"][y]), vecinos, x, y, paleta
    )
    st.pyplot(figura, width="content")


def _tabla_de_similares(vecinos: list[dict]) -> None:
    """El detalle de cada comparable, plegado.

    Con "en que se parecen" y "en que se separan": una lista de nombres y un
    porcentaje no se puede defender ante nadie; con los ejes, si.
    """
    with st.expander(f"Detalle de los {len(vecinos)} comparables"):
        st.dataframe(
            [
                {
                    "Jugador": v["player"],
                    "Equipo": v["team"],
                    "Liga": v["league"],
                    "Minutos": v["minutes"],
                    "Parecido": f"{v['similarity']:.0f} %",
                    "Se parecen en": ", ".join(v["closest"]),
                    "Se separan en": ", ".join(v["furthest"]),
                }
                for v in vecinos
            ],
            hide_index=True,
            width="stretch",
        )


# --- Comparacion de dos jugadores -------------------------------------------


def _comparacion(perfil: dict, rival: dict, templates: list[dict], paleta: Palette) -> None:
    """Pinta a los dos jugadores sobre los mismos ejes."""
    ficha, ficha_rival = perfil["player"], rival["player"]
    plantilla = _plantilla(templates, ficha["position_group"])
    if not plantilla:
        st.info("Esta posicion no tiene grafico definido.")
        return

    datos = presentation.prepare_comparison(perfil, rival, plantilla)
    if not len(datos):
        st.info("Los dos jugadores no comparten metricas con percentil.")
        return

    grafico, panel = st.columns([3, 2], gap="large")

    with grafico:
        figura = charts.compare(
            datos,
            f"{ficha['player']} ({ficha['team']})",
            f"{ficha_rival['player']} ({ficha_rival['team']})",
            _subtitulo(perfil),
            paleta,
        )
        st.pyplot(figura, width="content")
        if datos.missing:
            st.caption("Sin datos para: " + ", ".join(datos.missing))
        _descargar_figura(
            figura,
            presentation.chart_filename(
                ficha["player"], "vs", ficha_rival["player"], ficha["season"]
            ),
        )

    with panel:
        st.markdown(f"###### {ficha['player']}")
        st.markdown(presentation.summarise_profile(perfil))
        st.markdown(f"###### {ficha_rival['player']}")
        st.markdown(presentation.summarise_profile(rival))
        if perfil["caveats"]:
            with st.popover("Advertencias de lectura", width="stretch"):
                for aviso in perfil["caveats"]:
                    st.warning(aviso, icon=":material/info:")


# --- Mercado ----------------------------------------------------------------


def _mercado(ficha: dict) -> None:
    """Ficha, valor de mercado y carrera del jugador, segun Transfermarkt.

    Va en su propia pestana y no junto al grafico porque responde a otra
    pregunta. El pizza chart dice como juega; esto dice quien es: que edad
    tiene, cuanto vale, de donde viene y hasta cuando esta atado. Un percentil
    95 no significa lo mismo a los 19 anos que a los 33.
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

    curva, carrera = st.columns([3, 2], gap="large")

    tasaciones = datos["valuations"]
    with curva:
        if tasaciones:
            st.markdown("###### Curva de valor")
            # El eje va por FECHA y no por el orden de la tasacion. Con un indice
            # del 1 al 16, dos jugadores con el mismo numero de tasaciones salian
            # con curvas identicas de ancho aunque una cubriera diez anos y la
            # otra dos, y no se veia cuando subio ni a que edad.
            serie = pd.DataFrame(
                {"Millones de euros": [(v["market_value_eur"] or 0) / 1e6 for v in tasaciones]},
                index=pd.to_datetime([v["valuation_date"] for v in tasaciones]),
            )
            serie.index.name = "Fecha de tasacion"
            # La curva dice mas que la cifra: distingue al canterano en subida
            # del veterano en caida, aunque hoy valgan lo mismo.
            st.line_chart(serie, height=260)

    fichajes = datos["transfers"]
    with carrera:
        if fichajes:
            st.markdown("###### Carrera")
            st.dataframe(
                [
                    {
                        "Fecha": f["transfer_date"],
                        "Desde": f["club_from"],
                        "Hasta": f["club_to"],
                        "Importe": _millones(f["fee_eur"]),
                    }
                    for f in reversed(fichajes)
                ],
                hide_index=True,
                width="stretch",
                height=260,
            )
        elif not datos["caveats"]:
            st.caption("Sin fichajes registrados: puede llevar toda su carrera en el mismo club.")


def _millones(valor: float | None) -> str:
    """Un importe en millones, que es como se habla de esto en futbol."""
    if valor is None:
        return "-"
    return f"{valor / 1e6:,.1f} M EUR".replace(",", ".")


def _plantel(temporada: str, liga: str, equipo: str, paleta: Palette) -> None:
    """Edad y valor de toda la plantilla, no solo del jugador elegido.

    Responde a una pregunta que el perfil individual no puede responder: si el
    patrimonio del club esta en gente que aun va a subir o en gente que ya solo
    puede bajar, y si hay un agujero generacional entre los veteranos y la
    cantera.
    """
    try:
        jugadores = cached_squad(equipo, temporada, liga)
    except ApiError as error:
        st.error(str(error))
        return

    con_datos = [
        (j["player"], j["age"], j["market_value_eur"])
        for j in jugadores
        if j["age"] is not None and j["market_value_eur"]
    ]
    if not con_datos:
        st.info(
            "Sin edad ni valor de mercado para esta plantilla. Lanza la carga de "
            "Transfermarkt: `--profile transfermarkt ... --solo-equipos`."
        )
        return

    grafico, panel = st.columns([3, 2], gap="large")

    with grafico:
        figura = charts.squad_age_value(con_datos, paleta)
        st.pyplot(figura, width="content")

    with panel:
        edades = [e for _, e, _ in con_datos]
        valores = [v for _, _, v in con_datos]
        columnas = st.columns(2)
        columnas[0].metric("Edad media", f"{sum(edades) / len(edades):.1f}")
        columnas[1].metric("Valor total", _millones(sum(valores)))

        jovenes = [j for j in con_datos if j[1] <= 23]
        veteranos = [j for j in con_datos if j[1] >= 30]
        st.markdown(
            '<div class="panel-detalle">'
            '<div class="titulo">Reparto por edad</div>'
            f'<div class="valor">{len(jovenes)} de 23 o menos &middot; '
            f"{len(veteranos)} de 30 o mas</div></div>",
            unsafe_allow_html=True,
        )
        peso_joven = sum(v for _, e, v in con_datos if e <= 23) / sum(valores) * 100
        st.markdown(
            '<div class="panel-detalle">'
            '<div class="titulo">Patrimonio en menores de 24</div>'
            f'<div class="valor">{peso_joven:.0f} % del valor de la plantilla</div></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Un valor alto aqui suele significar que el club aun puede revalorizar; "
            "uno bajo, que su patrimonio ya solo puede depreciarse."
        )

    with st.expander(f"Plantilla completa ({len(jugadores)} jugadores)"):
        st.dataframe(
            [
                {
                    "Jugador": j["player"],
                    "Edad": j["age"],
                    "Posicion": j["position"],
                    "Valor": _millones(j["market_value_eur"]),
                }
                for j in sorted(jugadores, key=lambda x: x["market_value_eur"] or 0, reverse=True)
            ],
            hide_index=True,
            width="stretch",
        )


# --- Utilidades -------------------------------------------------------------


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


def _detalle(perfil: dict) -> None:
    """Tabla con el valor numerico, para quien quiera el dato y no el percentil."""
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

    st.caption(
        "Las metricas sin direccion (las tarjetas, los tiros) tienen percentil pero no "
        "significan mejor ni peor: describen como juega."
    )
    st.dataframe(filas[columnas].round(2), hide_index=True, width="stretch")


def _tabla(perfil: dict) -> None:
    """Detalle numerico plegado, para las posiciones sin grafico."""
    with st.expander("Detalle numerico"):
        _detalle(perfil)
