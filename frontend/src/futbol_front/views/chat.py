"""Asistente conversacional.

Habla con el mismo backend que el resto de la interfaz: la única diferencia es
que aquí hay un modelo de lenguaje de por medio, y por tanto la única respuesta
del proyecto que no es reproducible. Por eso cada turno enseña qué herramientas
ha consultado — es lo que permite comprobar de dónde sale un número sin fiarse
de lo que dice el modelo.

**El historial vive en la sesión, no en la API.** Es una conversación de una
sola persona con una sola pestaña abierta; guardarlo en el servidor no aportaría
nada y complicaría lo que hoy es un simple `st.session_state`.
"""

from __future__ import annotations

import streamlit as st

from futbol_front.client import ApiError
from futbol_front.presentation import season_label
from futbol_front.state import cached_catalog, cached_chat_status, get_client
from futbol_front.theme import apply

HISTORIAL = "chat_historial"

# Turnos que se mandan de vuelta a la API. El esquema los acota a 10; se manda
# algo menos para dejar sitio a la pregunta de este turno sin rozar el límite.
MAX_HISTORIAL_ENVIADO = 8

EJEMPLOS = [
    "¿Cómo es el perfil de Pedri esta temporada?",
    "¿Quién destaca en xA entre los centrocampistas?",
    "¿Cómo juega el Barcelona?",
]


def render() -> None:
    # Responde tanto sobre jugadores como sobre equipos: ninguna paleta de liga
    # encaja mejor que la neutra.
    apply(None)

    st.subheader("Asistente")
    st.caption(
        "Responde consultando los mismos datos que el resto de la plataforma, nunca "
        "de memoria. Cada respuesta dice qué ha consultado, para poder comprobarla."
    )

    try:
        catalogo = cached_catalog()
    except ApiError as error:
        st.error(f"La API no responde: {error}")
        return

    if not catalogo["seasons"]:
        st.warning("No hay datos cargados todavía.")
        return

    try:
        estado = cached_chat_status()
    except ApiError as error:
        st.error(f"No se ha podido comprobar el asistente: {error}")
        return

    if not estado.get("available"):
        st.warning(
            f"El modelo local ({estado.get('model', 'sin nombre')}) no está disponible. "
            "Levanta Ollama con `docker compose --profile chat up -d ollama` y descarga "
            f"el modelo con `docker compose exec ollama ollama pull {estado.get('model', '')}`."
        )
        return

    temporada = _temporada(catalogo)
    st.session_state.setdefault(HISTORIAL, [])

    _pintar_historial()
    if not st.session_state[HISTORIAL]:
        _sugerencias()

    pregunta = st.chat_input("Pregunta sobre jugadores, equipos o estilos de juego…")
    if pregunta:
        _responder(pregunta, temporada)
        st.rerun()


def _temporada(catalogo: dict) -> str:
    """La temporada sobre la que pregunta el asistente, elegible arriba como
    en el resto de la interfaz."""
    with st.container(border=True):
        return st.selectbox(
            "Temporada",
            catalogo["seasons"],
            index=len(catalogo["seasons"]) - 1,
            format_func=season_label,
            key="chat_temporada",
        )


def _pintar_historial() -> None:
    for turno in st.session_state[HISTORIAL]:
        with st.chat_message(turno["role"]):
            st.markdown(turno["content"])
            if turno.get("tools_used"):
                st.caption("Consultado: " + ", ".join(turno["tools_used"]))


def _sugerencias() -> None:
    """Ejemplos de pregunta, para no dejar una caja de texto vacía sin pistas
    de lo que el asistente sabe responder de verdad."""
    st.caption("Por ejemplo:")
    for ejemplo in EJEMPLOS:
        st.caption(f"· {ejemplo}")


def _responder(pregunta: str, temporada: str) -> None:
    """Llama al asistente y guarda el turno, tanto si responde como si no."""
    historial_previo = [
        {"role": turno["role"], "content": turno["content"]}
        for turno in st.session_state[HISTORIAL][-MAX_HISTORIAL_ENVIADO:]
    ]
    st.session_state[HISTORIAL].append({"role": "user", "content": pregunta})

    try:
        with st.spinner("Consultando…"):
            respuesta = get_client().ask_chat(pregunta, temporada, historial_previo)
    except ApiError as error:
        st.session_state[HISTORIAL].append(
            {"role": "assistant", "content": f"No se ha podido responder: {error}"}
        )
        return

    st.session_state[HISTORIAL].append(
        {
            "role": "assistant",
            "content": respuesta["reply"],
            "tools_used": respuesta.get("tools_used", []),
        }
    )
