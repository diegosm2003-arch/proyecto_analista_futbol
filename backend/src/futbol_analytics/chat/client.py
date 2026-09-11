"""Cliente de Ollama.

Capa fina: manda mensajes y devuelve lo que contesta el modelo. No interpreta
nada, que es cosa de `agent`.

Se usa `urllib` y no una librería de cliente porque la API de Ollama son dos
llamadas HTTP con JSON, y el proyecto ya paga esa decisión en el cliente de
Transfermarkt: añadir una dependencia para dos peticiones no sale a cuenta.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from futbol_analytics.config import get_settings

logger = logging.getLogger(__name__)

# Un modelo pequeno en CPU tarda. El limite es generoso a proposito: cortar a
# los treinta segundos daria un error donde solo hacia falta esperar.
TIMEOUT = 180

# Temperatura baja: esto no escribe cronicas, contesta sobre datos. Cuanto mas
# creativo, mas se aparta de lo que dice la herramienta.
TEMPERATURE = 0.2


class OllamaError(RuntimeError):
    """El modelo local no ha podido responder."""


class OllamaClient:
    """Acceso al modelo local."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = TIMEOUT,
    ) -> None:
        ajustes = get_settings()
        self.base_url = (base_url or ajustes.ollama_base_url).rstrip("/")
        self.model = model or ajustes.ollama_model
        self.timeout = timeout

    def available(self) -> bool:
        """Si Ollama responde y tiene el modelo descargado.

        Se comprueba antes de ofrecer el chat: es mejor decir que no está
        disponible que dejar al usuario escribiendo una pregunta que va a fallar.
        """
        try:
            etiquetas = self._post("/api/tags", None, method="GET")
        except OllamaError:
            return False
        modelos = {m.get("name", "") for m in etiquetas.get("models", [])}
        return any(nombre.startswith(self.model.split(":")[0]) for nombre in modelos)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Una vuelta de conversación. Devuelve el mensaje del modelo."""
        cuerpo: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": TEMPERATURE},
        }
        if tools:
            cuerpo["tools"] = tools

        respuesta = self._post("/api/chat", cuerpo)
        return respuesta.get("message", {})

    def _post(
        self, ruta: str, cuerpo: dict[str, Any] | None, method: str = "POST"
    ) -> dict[str, Any]:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        peticion = urllib.request.Request(
            f"{self.base_url}{ruta}",
            data=datos,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                return json.loads(respuesta.read())
        except urllib.error.HTTPError as error:
            raise OllamaError(f"Ollama ha devuelto {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise OllamaError(str(error)) from error
