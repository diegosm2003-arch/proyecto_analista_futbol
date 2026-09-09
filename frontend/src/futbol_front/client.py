"""Cliente de la API.

Streamlit no lee PostgreSQL: todo pasa por aqui. El modulo no importa
`streamlit` a proposito, para que se pueda testear sin levantar la interfaz; el
cacheo de las respuestas se aplica en las vistas.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20


class ApiError(RuntimeError):
    """La API ha respondido con un error o no ha respondido.

    Lleva el mensaje que da la API porque suele ser accionable ("indica el
    equipo", "no supera el umbral de minutos"), y esconderlo detras de un error
    generico obligaria a mirar los logs del contenedor.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    """Acceso a los endpoints de FastAPI."""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # --- Catalogo ---------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def catalog(self) -> dict[str, Any]:
        return self._get("/meta/catalog")

    def metrics(self) -> list[dict[str, Any]]:
        return self._get("/meta/metrics")

    def roles(self) -> list[dict[str, Any]]:
        return self._get("/meta/roles")

    def templates(self) -> list[dict[str, Any]]:
        return self._get("/meta/templates")

    # --- Jugadores --------------------------------------------------------

    def search_players(
        self,
        season: str,
        league: str | None = None,
        team: str | None = None,
        position_group: str | None = None,
        role: str | None = None,
        name: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/players",
            params={
                "season": season,
                "league": league,
                "team": team,
                "position_group": position_group,
                "role": role,
                "name": name,
                "limit": limit,
            },
        )

    def player_profile(
        self,
        player: str,
        season: str,
        team: str | None = None,
        basis: str = "per90",
        population: str = "position",
    ) -> dict[str, Any]:
        # El nombre va en la ruta y casi siempre lleva espacios o acentos, asi
        # que hay que escaparlo entero: sin `safe=""` una barra en el nombre
        # partiria la ruta.
        ruta = f"/players/{quote(player, safe='')}/profile"
        return self._get(
            ruta,
            params={
                "season": season,
                "team": team,
                "basis": basis,
                "population": population,
            },
        )

    def player_market(
        self,
        player: str,
        season: str,
        team: str | None = None,
    ) -> dict[str, Any]:
        """Ficha, valor de mercado y carrera de un jugador."""
        ruta = f"/players/{quote(player, safe='')}/market"
        return self._get(ruta, params={"season": season, "team": team})

    def player_similar(
        self,
        player: str,
        season: str,
        team: str | None = None,
        basis: str = "per90",
        limit: int = 6,
    ) -> dict[str, Any]:
        """Jugadores con un perfil parecido."""
        ruta = f"/players/{quote(player, safe='')}/similar"
        return self._get(
            ruta, params={"season": season, "team": team, "basis": basis, "limit": limit}
        )

    # --- Equipos ----------------------------------------------------------

    def teams(self, season: str, league: str | None = None) -> list[dict[str, Any]]:
        """Equipos de una temporada, con escudo."""
        return self._get("/teams", params={"season": season, "league": league})

    def squad(self, team: str, season: str, league: str) -> list[dict[str, Any]]:
        """Plantilla de un equipo con edad y valor de mercado."""
        ruta = f"/teams/{quote(team, safe='')}/squad"
        return self._get(ruta, params={"season": season, "league": league})

    def team_styles(
        self,
        season: str,
        league: str | None = None,
        n_styles: int = 5,
    ) -> dict[str, Any]:
        return self._get(
            "/teams/styles",
            params={"season": season, "league": league, "n_styles": n_styles},
        )

    # --- Interno ----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Peticion GET con los errores traducidos a `ApiError`."""
        # Los filtros sin valor no se envian: `league=None` en la query seria la
        # cadena "None" y no coincidiria con ninguna liga.
        limpios = {clave: valor for clave, valor in (params or {}).items() if valor is not None}

        try:
            respuesta = requests.get(f"{self.base_url}{path}", params=limpios, timeout=self.timeout)
        except requests.RequestException as error:
            raise ApiError(f"No se ha podido contactar con la API: {error}") from error

        if respuesta.status_code >= 400:
            raise ApiError(_detail(respuesta), status_code=respuesta.status_code)

        return respuesta.json()


def _detail(respuesta: requests.Response) -> str:
    """Extrae el mensaje de error que da la API."""
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return f"Error {respuesta.status_code}"

    detalle = cuerpo.get("detail") if isinstance(cuerpo, dict) else None
    if isinstance(detalle, str):
        return detalle
    if detalle:
        # Errores de validacion de FastAPI: llegan como lista de problemas.
        return "; ".join(str(problema.get("msg", problema)) for problema in detalle)
    return f"Error {respuesta.status_code}"
