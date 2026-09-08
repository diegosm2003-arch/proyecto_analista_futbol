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
    ) -> None:
        self._players = players
        self._teams = teams
        self._version = version
        self._runs = runs if runs is not None else [_ejecucion_correcta()]

    def version(self) -> str:
        return self._version

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


LIGAS = [
    "ESP-La Liga",
    "ENG-Premier League",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

# Perfiles con los que se generan defensas y centrocampistas distinguibles. Solo
# hacen falta valores separados: el objetivo es probar la API, no el clustering.
PERFILES = {
    "DF": {"def": 0.60, "mid": 0.32, "att": 0.08, "cross": 0.004, "prog": 0.08},
    "MF": {"def": 0.30, "mid": 0.50, "att": 0.20, "cross": 0.010, "prog": 0.13},
    "FW": {"def": 0.10, "mid": 0.30, "att": 0.60, "cross": 0.020, "prog": 0.06},
}


def _jugador(indice: int, position_group: str, liga: str, minutos: int) -> dict:
    """Una fila de `player_season` coherente con el catalogo de metricas."""
    perfil = PERFILES[position_group]
    generador = np.random.default_rng(indice)
    ruido = 1.0 + generador.normal(0.0, 0.05)
    toques, pases, conducciones, entradas = 1200.0, 900.0, 350.0, 60.0

    return {
        "league": liga,
        "season": "2526",
        "team": f"Equipo {indice % 10}",
        "player": f"{position_group} {indice}",
        "position_group": position_group,
        "detailed_position": None,
        "nation": "ESP",
        "age": 25,
        "born": 2000,
        "minutes": minutos,
        "matches_played": 30,
        "starts": 28,
        "touches": toques,
        "touches_def_third": toques * perfil["def"] * ruido,
        "touches_mid_third": toques * perfil["mid"] * ruido,
        "touches_att_third": toques * perfil["att"] * ruido,
        "touches_att_pen": toques * perfil["att"] * 0.1 * ruido,
        "passes_attempted": pases,
        "passes_completed": pases * 0.85,
        "progressive_passes": pases * perfil["prog"] * ruido,
        "passes_into_final_third": pases * 0.08 * ruido,
        "passes_into_penalty_area": pases * 0.02 * ruido,
        "crosses_into_penalty_area": pases * perfil["cross"] * ruido,
        "key_passes": pases * 0.02 * ruido,
        "progressive_pass_distance": 4000.0 * ruido,
        "xa": 2.0 * ruido,
        "take_ons_attempted": toques * 0.02 * ruido,
        "take_ons_successful": toques * 0.01 * ruido,
        "carries": conducciones,
        "carries_into_final_third": conducciones * 0.1 * ruido,
        "carries_into_penalty_area": conducciones * 0.03 * ruido,
        "passes_received": 700.0 * ruido,
        "progressive_carries": 40.0 * ruido,
        "progressive_passes_received": 90.0 * ruido,
        "shots": toques * 0.01 * ruido,
        "shots_on_target": toques * 0.004 * ruido,
        "avg_shot_distance": 17.0,
        "goals": 4.0 * ruido,
        "assists": 3.0 * ruido,
        "xg": 4.5 * ruido,
        "npxg": 4.0 * ruido,
        "xag": 3.2 * ruido,
        "shot_creating_actions": 60.0 * ruido,
        "goal_creating_actions": 8.0 * ruido,
        "tackles": entradas,
        "tackles_won": entradas * 0.6,
        "tackles_def_third": entradas * perfil["def"] * ruido,
        "tackles_mid_third": entradas * perfil["mid"] * ruido,
        "tackles_att_third": entradas * perfil["att"] * ruido,
        "dribblers_challenged": 40.0 * ruido,
        "dribblers_tackled": 20.0 * ruido,
        "blocks": 30.0 * ruido,
        "interceptions": 35.0 * ruido,
        "clearances": toques * perfil["def"] * 0.05 * ruido,
        "aerials_won": toques * perfil["def"] * 0.04 * ruido,
        "aerials_lost": toques * 0.01 * ruido,
        "ball_recoveries": 120.0 * ruido,
        "fouls_committed": 25.0 * ruido,
        "goals_against": None,
        "saves": None,
        "post_shot_xg": None,
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
    """Equipos con gradiente de posesion, en las dos perspectivas."""
    filas = []
    for i in range(10):
        propios = 350.0 + i * 50.0
        rivales = 1200.0 - propios
        for perspectiva, pases in (("for", propios), ("against", rivales)):
            filas.append(
                {
                    "league": "ESP-La Liga",
                    "season": "2526",
                    "team": f"Equipo {i}",
                    "perspective": perspectiva,
                    "minutes": 3420.0,
                    "matches_played": 38.0,
                    "passes_attempted": pases,
                    "passes_completed": pases * 0.85,
                    "passes_into_final_third": pases * 0.08,
                    "progressive_passes": pases * 0.1,
                    "progressive_carries": 500.0,
                    "touches_att_third": pases * 0.5,
                    "shots": 400.0 + i * 15.0,
                    "shots_on_target": 150.0,
                    "goals": 45.0,
                    "xg": 46.0,
                    "npxg": 42.0 + i * 2.0,
                    "tackles": 700.0 - i * 30.0,
                    "tackles_att_third": (700.0 - i * 30.0) * (0.1 + i * 0.02),
                    "interceptions": 300.0 - i * 8.0,
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
