"""Cliente del servicio `transfermarkt-api`.

Capa fina: pide y devuelve JSON. No interpreta nada, que es cosa de `parser`.

El servicio ya limita su propio ritmo contra Transfermarkt, pero puede devolver
429 si se le satura desde aqui. Por eso hay reintentos con espera creciente: un
429 no es un fallo, es una peticion de que vayamos mas despacio, y responder
insistiendo al mismo ritmo es la forma de convertirlo en un bloqueo.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from futbol_analytics.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = 40
MAX_ATTEMPTS = 4
# Espera inicial. Se dobla en cada reintento: 2, 4, 8 segundos.
BACKOFF_SECONDS = 2.0


class TransfermarktError(RuntimeError):
    """El servicio no ha podido responder."""


class PlayerNotFoundError(TransfermarktError):
    """Transfermarkt no conoce a ese jugador.

    Se distingue de un fallo de red a proposito: un jugador que no existe no se
    arregla reintentando, y no debe frenar al resto del lote.
    """


class TransfermarktClient:
    """Acceso al envoltorio de Transfermarkt."""

    def __init__(self, base_url: str | None = None, timeout: int = TIMEOUT) -> None:
        self.base_url = (base_url or get_settings().transfermarkt_url).rstrip("/")
        self.timeout = timeout

    def search_player(self, name: str) -> list[dict[str, Any]]:
        """Candidatos de Transfermarkt para un nombre."""
        ruta = f"/players/search/{urllib.parse.quote(name)}"
        try:
            return self._get(ruta).get("results", [])
        except PlayerNotFoundError:
            return []

    def competition_clubs(self, competition_id: str) -> list[dict[str, Any]]:
        """Clubes de una competicion en la temporada en curso.

        Es lo que permite no buscar clubes por nombre: los veinte de LaLiga
        vienen dados, asi que no hay forma de confundir el Barcelona con el
        Barcelona SC de Ecuador.
        """
        return self._get(f"/competitions/{competition_id}/clubs").get("clubs", [])

    def club_players(self, club_id: str) -> list[dict[str, Any]]:
        """Plantilla de un club, con la ficha de cada jugador.

        Trae de una vez lo que de otro modo serian decenas de busquedas, y
        ademas la ficha: fecha de nacimiento, posicion concreta, pie, fin de
        contrato y de donde llego cada uno.
        """
        return self._get(f"/clubs/{club_id}/players").get("players", [])

    def market_value(self, transfermarkt_id: str) -> dict[str, Any]:
        """Historico de valor de mercado."""
        return self._get(f"/players/{transfermarkt_id}/market_value")

    def transfers(self, transfermarkt_id: str) -> dict[str, Any]:
        """Historial de fichajes."""
        return self._get(f"/players/{transfermarkt_id}/transfers")

    def _get(self, ruta: str) -> dict[str, Any]:
        url = f"{self.base_url}{ruta}"
        espera = BACKOFF_SECONDS

        for intento in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as respuesta:
                    return json.load(respuesta)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise PlayerNotFoundError(f"Transfermarkt no tiene {ruta}.") from error
                if error.code not in (429, 500, 502, 503, 504) or intento == MAX_ATTEMPTS:
                    raise TransfermarktError(f"Error {error.code} en {ruta}.") from error
                logger.warning(
                    "Transfermarkt pide esperar",
                    extra={"ruta": ruta, "codigo": error.code, "intento": intento},
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if intento == MAX_ATTEMPTS:
                    raise TransfermarktError(f"No se ha podido leer {ruta}: {error}") from error
                logger.warning(
                    "Reintentando", extra={"ruta": ruta, "intento": intento, "motivo": str(error)}
                )

            time.sleep(espera)
            espera *= 2

        raise TransfermarktError(f"Agotados los intentos con {ruta}.")
