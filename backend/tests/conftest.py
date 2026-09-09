"""Fixtures compartidas."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from futbol_analytics.api import cache
from futbol_analytics.api.dependencies import get_data_access
from futbol_analytics.api.main import app
from futbol_analytics.api.repository import NO_DATA_VERSION


@pytest.fixture
def logging_intacto() -> Iterator[None]:
    """Restaura el logging raiz.

    `configure_logging` reconfigura el logger raiz por completo, asi que
    cualquier test que lo dispare (directamente o via el lifespan de la API)
    debe dejarlo como estaba para no afectar al resto de la suite.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _ejecucion_correcta() -> dict:
    """Una carga del ETL terminada con exito."""
    momento = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
    return {
        "id": 1,
        "status": "success",
        "started_at": momento,
        "finished_at": momento + timedelta(minutes=12),
        "leagues": "ESP-La Liga",
        "seasons": "2526",
        "player_rows": 123,
        "team_rows": 20,
        "error": None,
    }


class FakeDataAccess:
    """Acceso a datos en memoria, para testear la API sin PostgreSQL."""

    def __init__(
        self,
        players: pd.DataFrame,
        teams: pd.DataFrame,
        version: str = "v1",
        runs: list[dict] | None = None,
        market: dict | None = None,
    ) -> None:
        self._players = players
        self._teams = teams
        self._version = version
        self._runs = runs if runs is not None else [_ejecucion_correcta()]
        # Por defecto, un jugador sin cruzar con Transfermarkt: es el estado
        # normal mientras la carga no haya llegado a el.
        self._market = market or {"profile": None, "market_value": [], "transfers": []}

    def ensure_schema(self) -> None:
        """No hay esquema que crear: los datos viven en DataFrames."""

    def version(self) -> str:
        # Sin cargas correctas, igual que el repositorio real.
        return self._version if self._runs else NO_DATA_VERSION

    def seasons(self) -> list[str]:
        return sorted(self._players["season"].unique())

    def leagues(self) -> list[str]:
        return sorted(self._players["league"].unique())

    def players(self, season: str) -> pd.DataFrame:
        return self._players[self._players["season"] == season].copy()

    def teams(self, season: str) -> pd.DataFrame:
        return self._teams[self._teams["season"] == season].copy()

    def last_runs(self, limit: int = 5) -> list[dict]:
        return self._runs[:limit]

    def market(self, understat_id: str) -> dict:
        return self._market


LIGAS = [
    "ESP-La Liga",
    "ENG-Premier League",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

# Perfiles con los que se generan defensas y centrocampistas distinguibles. Solo
# hacen falta valores separados: el objetivo es probar la API, no el clustering.
# Perfiles ofensivos con los que se generan jugadores distinguibles. Solo hacen
# falta valores separados: el objetivo es probar la API, no el clustering.
PERFILES = {
    "DF": {"remate": 0.05, "asistencia": 0.15, "construccion": 0.80},
    "MF": {"remate": 0.25, "asistencia": 0.35, "construccion": 0.40},
    "FW": {"remate": 0.70, "asistencia": 0.15, "construccion": 0.15},
}

# Posicion tal y como la escribe Understat: letras sueltas, con "S" de suplente.
POSICION_CRUDA = {"DF": "D S", "MF": "M S", "FW": "F S"}


def _jugador(indice: int, position_group: str, liga: str, minutos: int) -> dict:
    """Una fila de `player_season` coherente con el catalogo de Understat."""
    perfil = PERFILES[position_group]
    generador = np.random.default_rng(indice)
    ruido = 1.0 + generador.normal(0.0, 0.05)
    cadena = 6.0
    np_xg = cadena * perfil["remate"] * ruido

    return {
        "league": liga,
        "season": "2526",
        "team": f"Equipo {indice % 10}",
        "player": f"{position_group} {indice}",
        "position_group": position_group,
        "position_raw": POSICION_CRUDA[position_group],
        "detailed_position": None,
        "nation": None,
        "age": None,
        "born": None,
        "minutes": minutos,
        "matches_played": 30,
        "goals": np_xg * 1.05,
        "np_goals": np_xg * 1.02,
        "np_xg": np_xg,
        "shots": 40.0 * ruido,
        "assists": cadena * perfil["asistencia"] * 0.8 * ruido,
        "xa": cadena * perfil["asistencia"] * ruido,
        "key_passes": 30.0 * ruido,
        "xg_chain": cadena * ruido,
        "xg_buildup": cadena * perfil["construccion"] * ruido,
        "yellow_cards": 4.0 * ruido,
        "red_cards": 0.0,
    }


@pytest.fixture
def jugadores() -> pd.DataFrame:
    """Poblacion sintetica: 5 ligas x 3 posiciones x 8 jugadores."""
    filas = []
    indice = 0
    for liga in LIGAS:
        for position_group in PERFILES:
            for _ in range(8):
                filas.append(_jugador(indice, position_group, liga, minutos=2000))
                indice += 1
    # Un suplente que no llega al umbral: existe, pero no es comparable.
    filas.append(_jugador(indice, "MF", "ESP-La Liga", minutos=90))
    filas[-1]["player"] = "Suplente"
    indice += 1

    # Un jugador traspasado en enero: dos etapas, dos filas. Su rendimiento
    # en cada club es un hecho distinto y la API no debe promediarlos.
    for equipo in ("Equipo 1", "Equipo 7"):
        filas.append(_jugador(indice, "MF", "ESP-La Liga", minutos=900))
        filas[-1]["player"] = "Traspasado"
        filas[-1]["team"] = equipo
        indice += 1
    return pd.DataFrame(filas)


@pytest.fixture
def equipos() -> pd.DataFrame:
    """Equipos con gradiente de presion, en las dos perspectivas."""
    filas = []
    for i in range(10):
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "for",
                "matches_played": 38.0,
                "goals": 60.0 - i * 3,
                "xg": 58.0 - i * 3,
                "np_xg": 55.0 - i * 3,
                "deep_completions": 400.0 - i * 25,
                "ppda": 6.0 + i * 1.2,
            }
        )
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "against",
                "matches_played": 38.0,
                "goals": 30.0 + i * 2,
                "xg": 32.0 + i * 2,
                "np_xg": 30.0 + i * 2,
                "deep_completions": 200.0 + i * 20,
                "ppda": 12.0,
            }
        )
    return pd.DataFrame(filas)


@pytest.fixture
def client(
    jugadores: pd.DataFrame,
    equipos: pd.DataFrame,
    logging_intacto: None,
) -> Iterator[TestClient]:
    """Cliente de la API con datos en memoria y cache limpia."""
    cache.clear()
    app.dependency_overrides[get_data_access] = lambda: FakeDataAccess(jugadores, equipos)
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()
    cache.clear()
