"""El bucle de conversación con el modelo local.

Un modelo de 3B no es un agente: es un clasificador con buena redacción. Todo lo
que hay aquí sale de asumir eso.

**Tope de vueltas.** Sin él, un modelo pequeño se queda pidiendo la misma
herramienta una y otra vez cuando la respuesta no le gusta. Se le dan dos
oportunidades de llamar a herramientas y a la tercera se le obliga a contestar
con lo que tenga.

**El prompt del sistema es corto.** Cada instrucción que se le añade compite por
atención con la pregunta del usuario. Las advertencias de lectura no van aquí:
viajan pegadas al resultado de cada herramienta, que es donde el modelo las ve
justo antes de escribir.

**Si no hay dato, se dice.** La instrucción más importante del prompt no es cómo
responder, sino qué hacer cuando no sabe. Un modelo pequeño rellena huecos con
plausibilidad, y en una herramienta de análisis un número inventado es peor que
un "no lo sé".

**La temporada no se le pide al modelo, se le impone.** Pedirle en el prompt que
no invente la temporada no basta: un jugador o un equipo conocido arrastra
consigo lo que el modelo aprendió de memoria sobre él, temporada incluida, y lo
repite aunque la herramienta le haya dado otra justo delante. La única forma
que ha funcionado es no dejarle la última palabra: se reescribe cualquier
temporada que mencione por la que de verdad usó la herramienta.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from futbol_analytics.api.repository import DataAccess
from futbol_analytics.chat import tools
from futbol_analytics.chat.client import OllamaClient, OllamaError
from futbol_analytics.seasons import season_label

logger = logging.getLogger(__name__)

# Vueltas de herramienta antes de obligar a contestar. Dos bastan para las
# preguntas que este chat sabe responder —mirar a un jugador, o a dos— y evitan
# que el modelo se quede en bucle pidiendo lo mismo.
MAX_TOOL_ROUNDS = 2

# Las cuatro herramientas empiezan su respuesta con "En la temporada X": es la
# unica fuente fiable de que temporada se ha usado de verdad.
_TEMPORADA_DEL_DATO = re.compile(r"[Ee]n la temporada (\d{4})")

# Cualquier mencion de temporada en la respuesta del modelo, para sustituirla.
# Va siempre pegada a la palabra "temporada": limitarlo a eso evita tocar un
# numero de minutos o un percentil que por casualidad tenga cuatro cifras.
_TEMPORADA_EN_TEXTO = re.compile(r"(?i)(temporada\s+)(\d{2,4}(?:[-/]\d{2,4})?)")

SYSTEM_PROMPT = """Eres un analista de fútbol. Respondes en español, breve y directo.

Usa las herramientas para consultar datos. Nunca inventes números ni nombres de
jugadores: si una herramienta no encuentra algo, dilo tal cual.

Si la herramienta devuelve un aviso sobre la muestra o los minutos, repítelo en
tu respuesta: es parte del dato.

No uses lo que sepas de memoria sobre jugadores o equipos, solo lo que diga la
herramienta. La única temporada que existe es la que aparece en su respuesta:
no la traduzcas a años, no la cambies, y no menciones ninguna otra."""


@dataclass(slots=True)
class ChatTurn:
    """Lo que devuelve una vuelta de conversación."""

    reply: str
    # Que herramientas se han usado, para que la interfaz lo pueda ensenar: un
    # chat sobre datos que no dice de donde saca lo que dice no es defendible.
    tools_used: list[str] = field(default_factory=list)


def answer(
    question: str,
    history: list[dict[str, Any]],
    data: DataAccess,
    season: str,
    client: OllamaClient,
) -> ChatTurn:
    """Responde a una pregunta, usando herramientas si hace falta."""
    mensajes: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": question},
    ]
    usadas: list[str] = []

    for vuelta in range(MAX_TOOL_ROUNDS + 1):
        # En la ultima vuelta se le quitan las herramientas: es la forma de
        # obligarle a contestar con lo que ya tiene en lugar de seguir pidiendo.
        ultima = vuelta == MAX_TOOL_ROUNDS
        try:
            respuesta = client.chat(mensajes, tools=None if ultima else tools.definitions())
        except OllamaError as error:
            logger.warning("El modelo no ha respondido", extra={"motivo": str(error)})
            return ChatTurn(
                reply=(
                    "El modelo local no responde. Comprueba que Ollama está levantado: "
                    "`docker compose --profile chat up -d ollama`."
                ),
                tools_used=usadas,
            )

        llamadas = respuesta.get("tool_calls") or []
        if not llamadas:
            texto = respuesta.get("content", "").strip()
            temporada_real = _ultima_temporada_citada(mensajes)
            if temporada_real:
                texto = _fuerza_temporada(texto, temporada_real)
            return ChatTurn(reply=texto, tools_used=usadas)

        mensajes.append(respuesta)
        for llamada in llamadas:
            nombre, argumentos = _leer_llamada(llamada)
            usadas.append(nombre)
            resultado = tools.dispatch(nombre, argumentos, data, season)
            logger.info(
                "Herramienta usada",
                extra={"herramienta": nombre, "argumentos": argumentos},
            )
            mensajes.append({"role": "tool", "content": resultado, "name": nombre})

    return ChatTurn(reply="No he sabido responder a eso.", tools_used=usadas)


def _leer_llamada(llamada: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Saca el nombre y los argumentos de una llamada a herramienta.

    Ollama devuelve los argumentos ya deserializados, pero algunos modelos los
    mandan como una cadena JSON. Se aceptan las dos formas en lugar de fiarse:
    fallar aquí rompe la conversación entera por un detalle de formato.
    """
    funcion = llamada.get("function", llamada)
    nombre = str(funcion.get("name", ""))
    crudos = funcion.get("arguments", {})

    if isinstance(crudos, str):
        try:
            crudos = json.loads(crudos)
        except json.JSONDecodeError:
            logger.warning("Argumentos ilegibles", extra={"herramienta": nombre})
            crudos = {}

    return nombre, crudos if isinstance(crudos, dict) else {}


def _ultima_temporada_citada(mensajes: list[dict[str, Any]]) -> str | None:
    """La temporada que de verdad se ha usado, leída del último resultado de
    herramienta y no de lo que el modelo escriba después.

    Se recorre en orden inverso porque, con dos vueltas de herramienta, la
    última es la que el modelo tiene más fresca al redactar la respuesta.
    """
    for mensaje in reversed(mensajes):
        if mensaje.get("role") != "tool":
            continue
        coincidencia = _TEMPORADA_DEL_DATO.search(str(mensaje.get("content", "")))
        if coincidencia:
            return coincidencia.group(1)
    return None


def _fuerza_temporada(texto: str, temporada: str) -> str:
    """Sustituye cualquier temporada que el modelo mencione por la real.

    Un modelo de 3B repite lo que sabe de memoria sobre jugadores y equipos
    conocidos, temporada incluida: siguió escribiendo "2023-2024" o "2023" con
    el dato de 2627 delante, incluso después de pedirle en el prompt que no lo
    hiciera. Corregir el texto final es lo único que ha funcionado.
    """
    etiqueta = season_label(temporada)
    return _TEMPORADA_EN_TEXTO.sub(rf"\g<1>{etiqueta}", texto)
