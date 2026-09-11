"""Endpoint del asistente conversacional.

Es el único sitio del proyecto donde hay un modelo de lenguaje, y por tanto el
único donde una respuesta puede no ser reproducible. Todo lo demás —percentiles,
clustering, similitud— da el mismo resultado con los mismos datos; esto no.

Por eso la respuesta dice **qué herramientas se han usado**: es lo que permite
comprobar de dónde sale cada número sin fiarse del modelo. Un chat sobre datos
que no enseña sus fuentes no es defendible en un proyecto cuyo mayor activo es
justamente el rigor.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import ChatAnswer, ChatQuestion, ChatStatus
from futbol_analytics.chat import agent
from futbol_analytics.chat.client import OllamaClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("", summary="Si el asistente está disponible")
def status_endpoint() -> ChatStatus:
    """Comprueba que Ollama responde y tiene el modelo descargado.

    Se consulta antes de ofrecer el chat en la interfaz: es mejor decir que no
    está disponible que dejar a alguien escribiendo una pregunta que va a
    fallar tras dos minutos de espera.
    """
    cliente = OllamaClient()
    return ChatStatus(available=cliente.available(), model=cliente.model)


@router.post("", summary="Preguntar al asistente")
def ask(pregunta: ChatQuestion, data: DataAccessDep) -> ChatAnswer:
    """Responde a una pregunta sobre los datos cargados.

    El modelo no escribe SQL ni ve la base de datos: elige entre cuatro
    herramientas con parámetros tipados, y cada una llama al mismo análisis que
    usa la interfaz.
    """
    cliente = OllamaClient()
    if not cliente.available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"El modelo {cliente.model!r} no está disponible. Levanta Ollama con "
                "`docker compose --profile chat up -d ollama` y descarga el modelo con "
                f"`docker compose exec ollama ollama pull {cliente.model}`."
            ),
        )

    turno = agent.answer(
        question=pregunta.question,
        history=[m.model_dump() for m in pregunta.history],
        data=data,
        season=pregunta.season,
        client=cliente,
    )
    logger.info(
        "Pregunta respondida",
        extra={"herramientas": turno.tools_used, "temporada": pregunta.season},
    )
    return ChatAnswer(reply=turno.reply, tools_used=turno.tools_used)
