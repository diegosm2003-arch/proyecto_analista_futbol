"""Navegacion en tres pasos: liga, equipo y jugador.

Sustituye a entrar directamente en un desplegable con doscientos nombres. La
diferencia no es estetica: un buscador exige saber a quien buscas, y buena parte
del trabajo de un analista es justo lo contrario —ver que hay en un equipo, en
una liga— antes de fijarse en nadie.

Los tres pasos comparten forma a proposito: una rejilla de fichas con escudo,
nombre y un dato de contexto. Aprender a leer una vale para las tres.

**El estado vive en la sesion y no en la URL.** Volver atras desde el equipo
conserva la liga, y cambiar de ambito conserva las dos, que es como se trabaja
de verdad: se mira a los delanteros del Betis y despues al Betis entero.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from futbol_front.theme import LEAGUE_LOGOS, UPCOMING_LEAGUES, Palette

LIGA = "liga_elegida"
EQUIPO = "equipo_elegido"

# Fichas por fila. Cinco entran comodas en pantalla ancha y dejan el nombre del
# club en una sola linea en casi todos los casos.
POR_FILA = 5


def liga_actual() -> str | None:
    return st.session_state.get(LIGA)


def equipo_actual() -> str | None:
    return st.session_state.get(EQUIPO)


def elegir_liga(liga: str | None) -> None:
    st.session_state[LIGA] = liga
    # Cambiar de liga invalida el equipo: un equipo de otra liga no existe aqui.
    st.session_state[EQUIPO] = None


def elegir_equipo(equipo: str | None) -> None:
    st.session_state[EQUIPO] = equipo


def migas(paleta: Palette) -> None:
    """Rastro de navegacion, con vuelta a cada paso.

    Se pinta siempre, tambien cuando no hay nada elegido, para que la pantalla
    no cambie de altura al avanzar: un salto vertical en cada paso hace que el
    contenido baile.
    """
    liga, equipo = liga_actual(), equipo_actual()
    if liga is None:
        return

    volver_liga, volver_equipo, _ = st.columns([1, 1, 5])
    with volver_liga:
        st.button(
            "Todas las ligas",
            icon=":material/arrow_back:",
            width="stretch",
            on_click=elegir_liga,
            args=(None,),
        )
    if equipo is not None:
        with volver_equipo:
            st.button(
                paleta.name,
                icon=":material/arrow_back:",
                width="stretch",
                on_click=elegir_equipo,
                args=(None,),
            )


def selector_de_liga(leagues: list[str], titulo: str) -> None:
    """Rejilla de ligas disponibles."""
    st.subheader(titulo)
    st.caption(
        "Los percentiles se calculan siempre contra las cinco grandes; la liga solo "
        "filtra a quien se enseña."
    )

    columnas = st.columns(min(len(leagues), POR_FILA), gap="medium")
    for columna, liga in zip(columnas, leagues, strict=False):
        with columna, st.container(border=True):
            st.markdown(
                _ficha(LEAGUE_LOGOS.get(liga), _nombre_corto(liga), ""),
                unsafe_allow_html=True,
            )
            st.button(
                "Entrar",
                key=f"liga-{liga}",
                width="stretch",
                on_click=elegir_liga,
                args=(liga,),
            )

    _proximas()


def _proximas() -> None:
    """Ligas que aun no estan cargadas.

    Se ensenan porque una rejilla con cinco fichas y nada mas no dice si eso es
    todo lo que va a haber. Van atenuadas y sin boton para que se lean como un
    anuncio y no como algo en lo que se pueda entrar y falle.
    """
    st.divider()
    st.caption("Próximamente")

    columnas = st.columns(len(UPCOMING_LEAGUES), gap="medium")
    for columna, (nombre, logo) in zip(columnas, UPCOMING_LEAGUES, strict=False):
        with columna:
            st.markdown(
                f'<div class="ficha-proxima">'
                f'<img src="{logo}" alt="{nombre}" loading="lazy">'
                f'<div class="nombre">{nombre}</div>'
                f'<div class="etiqueta">Proximamente</div></div>',
                unsafe_allow_html=True,
            )


def _nombre_corto(liga: str) -> str:
    """Nombre de liga sin el prefijo de pais.

    El catalogo las identifica como "ESP-La Liga" porque es lo que espera la
    fuente, pero debajo de su propio escudo el prefijo sobra y ademas corta el
    nombre en dos lineas.
    """
    return liga.split("-", 1)[-1] if "-" in liga else liga


def selector_de_equipo(equipos: list[dict[str, Any]], titulo: str) -> None:
    """Rejilla de equipos de la liga elegida."""
    st.subheader(titulo)
    if not equipos:
        st.info("No hay equipos cargados en esta liga y temporada.")
        return

    st.caption(f"{len(equipos)} equipos cargados. El número es la plantilla que tenemos.")

    for inicio in range(0, len(equipos), POR_FILA):
        fila = equipos[inicio : inicio + POR_FILA]
        columnas = st.columns(POR_FILA, gap="medium")
        for columna, equipo in zip(columnas, fila, strict=False):
            with columna, st.container(border=True):
                st.markdown(
                    _ficha(
                        equipo.get("crest_url"),
                        equipo["team"],
                        f"{equipo['squad_size']} jugadores",
                    ),
                    unsafe_allow_html=True,
                )
                st.button(
                    "Ver plantilla",
                    key=f"equipo-{equipo['team']}",
                    width="stretch",
                    on_click=elegir_equipo,
                    args=(equipo["team"],),
                )


def _ficha(logo: str | None, nombre: str, dato: str) -> str:
    """Escudo, nombre y un dato de contexto.

    Cuando no hay escudo se pinta un cuadro con las iniciales en lugar de un
    hueco: una rejilla con celdas vacias parece rota, y no todos los equipos
    cruzan con Transfermarkt (un ascendido, un filial).
    """
    if logo:
        imagen = f'<img src="{logo}" alt="{nombre}" loading="lazy">'
    else:
        iniciales = "".join(parte[0] for parte in nombre.split()[:2]).upper()
        imagen = f'<span class="sin-escudo">{iniciales}</span>'

    contexto = f'<div class="dato">{dato}</div>' if dato else ""
    return f'<div class="ficha-escudo">{imagen}<div class="nombre">{nombre}</div>{contexto}</div>'
