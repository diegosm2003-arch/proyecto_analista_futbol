"""Tests de la normalizacion por 90 minutos y por posesion."""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import features
from futbol_analytics.metrics import PLAYER_METRICS

ENTRADAS = next(m for m in PLAYER_METRICS if m.name == "tackles")
GOLES = next(m for m in PLAYER_METRICS if m.name == "goals")


def _jugadores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "league": ["ESP-La Liga", "ESP-La Liga"],
            "season": ["2526", "2526"],
            "team": ["Dominador", "Replegado"],
            "player": ["Pivote A", "Pivote B"],
            "position_group": ["MF", "MF"],
            "minutes": [1800, 1800],
            "tackles": [40.0, 40.0],
            "goals": [4.0, 2.0],
        }
    )


def _equipos(posesion: list[float] | None, pases: tuple[list[float], list[float]]) -> pd.DataFrame:
    propios, rivales = pases
    filas = {
        "league": ["ESP-La Liga"] * 4,
        "season": ["2526"] * 4,
        "team": ["Dominador", "Replegado", "Dominador", "Replegado"],
        "perspective": ["for", "for", "against", "against"],
        "passes_attempted": [*propios, *rivales],
        "minutes": [3420.0] * 4,
    }
    if posesion is not None:
        filas["possession_pct"] = [*posesion, float("nan"), float("nan")]
    return pd.DataFrame(filas)


# --- Por 90 -----------------------------------------------------------------


def test_per_90_divide_por_los_noventas_jugados() -> None:
    jugadores = _jugadores()

    resultado = features.per_90(jugadores, (ENTRADAS,))

    # 40 entradas en 1800 minutos = 20 partidos = 2 por 90.
    assert resultado["tackles_p90"].tolist() == [2.0, 2.0]


def test_per_90_no_divide_por_cero() -> None:
    jugadores = _jugadores()
    jugadores.loc[0, "minutes"] = 0

    resultado = features.per_90(jugadores, (ENTRADAS,))

    assert pd.isna(resultado.loc[0, "tackles_p90"])


def test_per_90_exige_los_minutos() -> None:
    with pytest.raises(KeyError, match="minutes"):
        features.per_90(_jugadores().drop(columns=["minutes"]), (ENTRADAS,))


def test_per_90_ignora_las_metricas_que_no_se_normalizan() -> None:
    minutos = next(m for m in PLAYER_METRICS if m.name == "minutes")

    resultado = features.per_90(_jugadores(), (minutos,))

    assert "minutes_p90" not in resultado.columns


# --- Posesion ---------------------------------------------------------------


def test_team_possession_usa_el_dato_de_fbref_si_existe() -> None:
    equipos = _equipos([65.0, 35.0], ([600.0, 300.0], [300.0, 600.0]))

    posesion = features.team_possession(equipos)

    assert posesion.loc[("ESP-La Liga", "2526", "Dominador")] == 65.0


def test_team_possession_cae_en_la_cuota_de_pases_si_falta() -> None:
    # Sin posesion publicada, un equipo que da 600 de los 900 pases del partido
    # tiene aproximadamente dos tercios del balon.
    equipos = _equipos(None, ([600.0, 300.0], [300.0, 600.0]))

    posesion = features.team_possession(equipos)

    assert posesion.loc[("ESP-La Liga", "2526", "Dominador")] == pytest.approx(66.67, abs=0.01)
    assert posesion.loc[("ESP-La Liga", "2526", "Replegado")] == pytest.approx(33.33, abs=0.01)


def test_team_possession_recorta_valores_imposibles() -> None:
    equipos = _equipos([95.0, 5.0], ([600.0, 300.0], [300.0, 600.0]))

    posesion = features.team_possession(equipos)

    assert posesion.max() <= features.MAX_POSSESSION
    assert posesion.min() >= features.MIN_POSSESSION


def test_team_possession_exige_las_claves_de_equipo() -> None:
    equipos = _equipos(None, ([600.0, 300.0], [300.0, 600.0])).drop(columns=["team"])

    with pytest.raises(KeyError, match="team"):
        features.team_possession(equipos)


# --- Ajuste por posesion ----------------------------------------------------


def test_el_ajuste_favorece_al_jugador_del_equipo_que_mas_balon_tiene() -> None:
    # Los dos pivotes hacen exactamente las mismas entradas por 90. El del
    # equipo dominador ha tenido mucho menos tiempo para hacerlas, asi que
    # ajustado vale mas. Sin este ajuste, el percentil defensivo premia jugar en
    # un equipo malo.
    jugadores = features.per_90(_jugadores(), (ENTRADAS,))
    posesion = features.team_possession(_equipos([65.0, 35.0], ([600.0, 300.0], [300.0, 600.0])))

    resultado = features.possession_adjust(jugadores, (ENTRADAS,), posesion)

    dominador = resultado.loc[resultado["team"] == "Dominador", "tackles_padj"].iloc[0]
    replegado = resultado.loc[resultado["team"] == "Replegado", "tackles_padj"].iloc[0]
    assert dominador > replegado
    # 2 por 90 con 65 % de posesion: 2 * 50 / 35.
    assert dominador == pytest.approx(2.0 * 50.0 / 35.0)


def test_un_equipo_con_el_50_por_ciento_no_se_ajusta() -> None:
    jugadores = features.per_90(_jugadores(), (ENTRADAS,))
    posesion = features.team_possession(_equipos([50.0, 50.0], ([450.0, 450.0], [450.0, 450.0])))

    resultado = features.possession_adjust(jugadores, (ENTRADAS,), posesion)

    assert resultado["tackles_padj"].tolist() == [2.0, 2.0]


def test_solo_se_ajustan_las_metricas_sensibles_a_la_posesion() -> None:
    # Los goles no dependen del tiempo sin balon: ajustarlos no tendria sentido.
    jugadores = features.per_90(_jugadores(), (ENTRADAS, GOLES))
    posesion = features.team_possession(_equipos([65.0, 35.0], ([600.0, 300.0], [300.0, 600.0])))

    resultado = features.possession_adjust(jugadores, (ENTRADAS, GOLES), posesion)

    assert "tackles_padj" in resultado.columns
    assert "goals_padj" not in resultado.columns


def test_sin_posesion_conocida_el_jugador_se_queda_sin_ajuste() -> None:
    jugadores = features.per_90(_jugadores(), (ENTRADAS,))
    # Posesion de un equipo que no es el suyo: no hay con que ajustar.
    posesion = pd.Series(
        [55.0],
        index=pd.MultiIndex.from_tuples(
            [("ENG-Premier League", "2526", "Otro")],
            names=["league", "season", "team"],
        ),
    )

    resultado = features.possession_adjust(jugadores, (ENTRADAS,), posesion)

    assert resultado["tackles_padj"].isna().all()


# --- Poblacion --------------------------------------------------------------


def test_eligible_descarta_muestras_pequenas_y_jugadores_sin_posicion() -> None:
    jugadores = pd.DataFrame(
        {
            "player": ["Titular", "Suplente", "Sin posicion"],
            "minutes": [2000, 120, 2000],
            "position_group": ["MF", "MF", None],
        }
    )

    resultado = features.eligible(jugadores, min_minutes=450)

    assert resultado["player"].tolist() == ["Titular"]
