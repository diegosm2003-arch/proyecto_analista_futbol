"""Tests del cliente de la API. No levantan ni la API ni Streamlit."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from futbol_front import client as modulo
from futbol_front.client import ApiClient, ApiError


class RespuestaFalsa:
    """Imita lo que devuelve `requests.get`."""

    def __init__(self, status_code: int = 200, payload: Any = None, texto: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._texto = texto

    def json(self) -> Any:
        if self._texto:
            raise ValueError("no es JSON")
        return self._payload


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Captura las peticiones en lugar de hacerlas."""
    registro: list[dict] = []

    def falso_get(url: str, params: dict | None = None, timeout: int | None = None):
        registro.append({"url": url, "params": params, "timeout": timeout})
        return RespuestaFalsa(payload={"ok": True})

    monkeypatch.setattr(modulo.requests, "get", falso_get)
    return registro


def test_la_url_base_no_duplica_la_barra(llamadas: list[dict]) -> None:
    ApiClient("http://api:8000/").health()

    assert llamadas[0]["url"] == "http://api:8000/health"


def test_los_filtros_vacios_no_se_envian(llamadas: list[dict]) -> None:
    # Sin esto, `league=None` viajaria como la cadena "None" y no coincidiria
    # con ninguna liga: la busqueda devolveria vacio sin explicar por que.
    ApiClient("http://api:8000").search_players(season="2526", league=None, name=None)

    assert "league" not in llamadas[0]["params"]
    assert "name" not in llamadas[0]["params"]
    assert llamadas[0]["params"]["season"] == "2526"


def test_el_nombre_del_jugador_se_escapa_en_la_ruta(llamadas: list[dict]) -> None:
    # Los nombres llevan espacios y acentos, y alguno lleva barra.
    ApiClient("http://api:8000").player_profile("Nico Williams", season="2526")

    assert llamadas[0]["url"] == "http://api:8000/players/Nico%20Williams/profile"


def test_una_barra_en_el_nombre_no_parte_la_ruta(llamadas: list[dict]) -> None:
    ApiClient("http://api:8000").player_profile("Ander/ Herrera", season="2526")

    assert "/players/Ander%2F%20Herrera/profile" in llamadas[0]["url"]


def test_se_manda_un_timeout(llamadas: list[dict]) -> None:
    # Sin timeout, una API colgada dejaria la interfaz bloqueada para siempre.
    ApiClient("http://api:8000", timeout=5).health()

    assert llamadas[0]["timeout"] == 5


def test_el_mensaje_de_la_api_llega_al_usuario(monkeypatch: pytest.MonkeyPatch) -> None:
    # Los mensajes de la API son accionables ("indica el equipo"), asi que no
    # deben esconderse detras de un error generico.
    detalle = "'Traspasado' tiene 2 etapas en '2526'. Indica el equipo."
    monkeypatch.setattr(
        modulo.requests,
        "get",
        lambda *a, **k: RespuestaFalsa(status_code=409, payload={"detail": detalle}),
    )

    with pytest.raises(ApiError, match="Indica el equipo") as error:
        ApiClient("http://api:8000").player_profile("Traspasado", season="2526")

    assert error.value.status_code == 409


def test_los_errores_de_validacion_se_resumen(monkeypatch: pytest.MonkeyPatch) -> None:
    cuerpo = {"detail": [{"msg": "Input should be 'per90' or 'padj'"}, {"msg": "otro"}]}
    monkeypatch.setattr(
        modulo.requests, "get", lambda *a, **k: RespuestaFalsa(status_code=422, payload=cuerpo)
    )

    with pytest.raises(ApiError, match="per90"):
        ApiClient("http://api:8000").health()


def test_un_error_sin_json_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        modulo.requests, "get", lambda *a, **k: RespuestaFalsa(status_code=502, texto=True)
    )

    with pytest.raises(ApiError, match="502"):
        ApiClient("http://api:8000").health()


def test_si_la_api_no_responde_se_explica(monkeypatch: pytest.MonkeyPatch) -> None:
    def falla(*_a, **_k):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(modulo.requests, "get", falla)

    with pytest.raises(ApiError, match="No se ha podido contactar"):
        ApiClient("http://api:8000").catalog()


def test_una_respuesta_correcta_se_devuelve_deserializada(llamadas: list[dict]) -> None:
    assert ApiClient("http://api:8000").catalog() == {"ok": True}


# --- La sonda de version ----------------------------------------------------


def test_si_la_api_no_contesta_la_version_no_revienta_la_interfaz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # La version del dato es la clave de toda la cache. Si /health falla un
    # momento, propagar el error dejaria en blanco una pantalla cuyos datos ya
    # estan cacheados; y devolver algo distinto cada vez invalidaria la cache
    # entera en cada interaccion.
    from futbol_front import state

    def revienta() -> dict:
        raise ApiError("API caida")

    monkeypatch.setattr(state, "cached_health", revienta)

    assert state.data_version() == state.UNKNOWN_VERSION
