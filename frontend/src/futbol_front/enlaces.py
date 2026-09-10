"""Cada análisis, un enlace.

La aplicación guarda su estado en la sesión, que es lo que permite volver atrás
sin perder la liga elegida. El precio de eso es que el estado no viaja: abrir la
misma pantalla en otro navegador exige repetir los cuatro clics, y compartir un
hallazgo obliga a explicar la ruta con palabras.

Aquí se sincroniza ese estado con los parámetros de la URL en las dos
direcciones. Al cargar, la URL manda; después, cada cambio se refleja en la
barra de direcciones. El resultado es que copiar la URL comparte exactamente lo
que se está viendo, que es lo que convierte cada análisis en algo publicable.

**Solo viaja lo que identifica la vista**, no todo el estado. La temporada, la
liga, el equipo y el jugador definen qué se está mirando; que un desplegable
esté abierto, no. Meter todo en la URL la haría ilegible y frágil, porque
cualquier control nuevo cambiaría el formato del enlace.
"""

from __future__ import annotations

import streamlit as st

# Clave de sesión -> nombre corto en la URL. El nombre corto se elige para que
# el enlace se lea: `?liga=ESP-La+Liga&equipo=Barcelona` dice de qué va antes de
# abrirlo, y eso importa cuando se comparte en un mensaje.
COMPARTIDO: dict[str, str] = {
    "destino": "vista",
    "liga_elegida": "liga",
    "equipo_elegido": "equipo",
    "temporada_activa": "temporada",
}

# Marca de que la URL ya se leyó. Sin ella, cada reejecución del script volvería
# a aplicar los parámetros originales y pisaría la navegación del usuario: al
# pulsar "volver a las ligas" reaparecería la liga que traía el enlace.
_LEIDO = "_url_leida"


def leer_una_vez() -> None:
    """Vuelca los parámetros de la URL en la sesión, la primera vez."""
    if st.session_state.get(_LEIDO):
        return
    st.session_state[_LEIDO] = True

    parametros = st.query_params
    for clave, nombre in COMPARTIDO.items():
        valor = parametros.get(nombre)
        if valor:
            st.session_state[clave] = valor


def escribir() -> None:
    """Refleja el estado actual en la barra de direcciones.

    Los valores vacíos se quitan en lugar de escribirse como cadena vacía: una
    URL con `?equipo=` no significa nada y ensucia el enlace.
    """
    nuevos = {
        nombre: str(st.session_state[clave])
        for clave, nombre in COMPARTIDO.items()
        if st.session_state.get(clave)
    }
    if dict(st.query_params) != nuevos:
        st.query_params.clear()
        st.query_params.update(nuevos)


def boton_de_copiado() -> None:
    """Enseña el enlace a la vista actual, listo para copiar.

    Se muestra el texto en lugar de copiarlo al portapapeles porque Streamlit no
    da acceso al portapapeles del navegador sin componentes de terceros, y el
    bloque de código ya trae su propio botón de copiar.
    """
    consulta = "&".join(f"{k}={v}" for k, v in st.query_params.items())
    if not consulta:
        return

    with st.popover("Compartir esta vista", width="stretch"):
        st.caption(
            "Pega esto donde quieras: abre la aplicación exactamente en esta pantalla, "
            "con la misma liga, equipo y temporada."
        )
        st.code(f"?{consulta}", language=None)
