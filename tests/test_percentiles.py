"""Tests de los percentiles por posicion.

El test que mas importa es el del orden: poblacion Big 5 primero, filtro a
LaLiga despues. Invertirlo no da un error, da un numero que parece bueno y no lo
es, que es la peor clase de fallo en un producto de analisis.
"""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import percentiles
from futbol_analytics.metrics import PLAYER_METRICS

GOLES = next(m for m in PLAYER_METRICS if m.name == "goals")
FALTAS = next(m for m in PLAYER_METRICS if m.name == "fouls_committed")
DESPEJES = next(m for m in PLAYER_METRICS if m.name == "clearances")

LIGAS = [
    "ESP-La Liga",
    "ENG-Premier League",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]


def _poblacion(valores: list[float], ligas: list[str], season: str = "2526") -> pd.DataFrame:
    """Una poblacion de mediocentros con los goles que se le indiquen."""
    return pd.DataFrame(
        {
            "league": ligas,
            "season": [season] * len(valores),
            "team": [f"Equipo {i}" for i in range(len(valores))],
            "player": [f"Jugador {i}" for i in range(len(valores))],
            "position_group": ["MF"] * len(valores),
            "minutes": [1800] * len(valores),
            "goals": valores,
            "fouls_committed": [10.0] * len(valores),
            "clearances": [10.0] * len(valores),
        }
    )


def test_el_percentil_se_calcula_contra_las_big_5_y_no_contra_laliga() -> None:
    # Dos jugadores de LaLiga: uno flojo (2 goles) y uno bueno (18). Dentro de
    # LaLiga el flojo seria la mitad de la muestra. Contra las Big 5 esta abajo.
    valores = [2.0, 18.0, 10.0, 12.0, 14.0, 16.0, 17.0, 19.0, 20.0, 22.0]
    ligas = ["ESP-La Liga", "ESP-La Liga", *(LIGAS[1:] * 2)]
    jugadores = _poblacion(valores, ligas)

    resultado = percentiles.compute(jugadores, (GOLES,), min_minutes=450)

    flojo = resultado[(resultado["player"] == "Jugador 0") & (resultado["metric"] == "goals")]
    # Si el percentil se hubiese calculado solo con LaLiga, seria 50.
    assert flojo["percentile_per90"].iloc[0] < 25.0


def test_cada_temporada_es_su_propia_poblacion() -> None:
    # El mismo rendimiento vale distinto segun contra quien se compare, y
    # comparar contra otra temporada es comparar con un futbol distinto.
    floja = _poblacion([10.0, 2.0, 3.0, 4.0, 5.0], LIGAS, season="2425")
    fuerte = _poblacion([10.0, 20.0, 30.0, 40.0, 50.0], LIGAS, season="2526")
    fuerte["player"] = [f"Otro {i}" for i in range(5)]

    resultado = percentiles.compute(
        pd.concat([floja, fuerte], ignore_index=True), (GOLES,), min_minutes=450
    )

    en_2425 = resultado[(resultado["player"] == "Jugador 0") & (resultado["season"] == "2425")]
    en_2526 = resultado[(resultado["player"] == "Otro 0") & (resultado["season"] == "2526")]
    assert en_2425["percentile_per90"].iloc[0] > en_2526["percentile_per90"].iloc[0]


def test_cada_posicion_es_su_propia_poblacion() -> None:
    # Un central no se compara con un delantero en goles: no mide lo mismo.
    jugadores = _poblacion([2.0, 4.0, 6.0, 8.0, 10.0], LIGAS)
    jugadores.loc[0, "position_group"] = "DF"

    resultado = percentiles.compute(jugadores, (GOLES,), min_minutes=450)

    central = resultado[resultado["player"] == "Jugador 0"]
    # Unico central de la poblacion: es el mejor y el peor de su grupo.
    assert central["percentile_per90"].iloc[0] == 100.0


def test_la_poblacion_se_filtra_antes_de_ordenar() -> None:
    # Un jugador con 60 minutos y un gol tiene 1,5 goles por 90, un ratio que no
    # significa nada. Si entrase en la poblacion, empujaria hacia abajo el
    # percentil de todos los demas.
    jugadores = _poblacion([2.0, 4.0, 6.0, 8.0, 10.0], LIGAS)
    jugadores.loc[0, "minutes"] = 60
    jugadores.loc[0, "goals"] = 1.0

    resultado = percentiles.compute(jugadores, (GOLES,), min_minutes=450)

    assert "Jugador 0" not in set(resultado["player"])
    assert len(resultado) == 4


def test_las_metricas_donde_menos_es_mejor_se_invierten() -> None:
    # Cometer menos faltas es mejor, asi que el percentil alto tiene que ir al
    # que menos comete. Sin invertir, el pizza chart premiaria al mas brusco.
    jugadores = _poblacion([5.0] * 5, LIGAS)
    jugadores["fouls_committed"] = [10.0, 20.0, 30.0, 40.0, 50.0]

    resultado = percentiles.compute(jugadores, (FALTAS,), min_minutes=450)
    perfil = resultado.set_index("player")["percentile_per90"]

    assert perfil["Jugador 0"] > perfil["Jugador 4"]


def test_las_metricas_de_estilo_no_se_invierten() -> None:
    # Despejar mucho no es bueno ni malo: describe donde defiende el equipo.
    jugadores = _poblacion([5.0] * 5, LIGAS)
    jugadores["clearances"] = [10.0, 20.0, 30.0, 40.0, 50.0]

    resultado = percentiles.compute(jugadores, (DESPEJES,), min_minutes=450)
    perfil = resultado.set_index("player")["percentile_per90"]

    assert perfil["Jugador 4"] > perfil["Jugador 0"]


def test_sin_posesion_no_hay_percentil_ajustado() -> None:
    entradas = next(m for m in PLAYER_METRICS if m.name == "tackles")
    jugadores = _poblacion([5.0] * 5, LIGAS)
    jugadores["tackles"] = [10.0, 20.0, 30.0, 40.0, 50.0]

    resultado = percentiles.compute(jugadores, (entradas,), min_minutes=450)

    assert resultado["percentile_per90"].notna().all()
    assert resultado["percentile_padj"].isna().all()


def test_una_poblacion_vacia_no_revienta() -> None:
    jugadores = _poblacion([5.0] * 5, LIGAS)
    jugadores["minutes"] = 10

    resultado = percentiles.compute(jugadores, (GOLES,), min_minutes=450)

    assert resultado.empty
    assert "percentile_per90" in resultado.columns


def test_for_player_devuelve_el_perfil_ordenado() -> None:
    jugadores = _poblacion([2.0, 4.0, 6.0, 8.0, 10.0], LIGAS)

    resultado = percentiles.compute(jugadores, (GOLES, FALTAS), min_minutes=450)
    perfil = percentiles.for_player(resultado, "Jugador 4", "2526")

    assert set(perfil["metric"]) == {"goals", "fouls_committed"}
    assert perfil["percentile_per90"].is_monotonic_decreasing


def test_for_player_rechaza_una_base_desconocida() -> None:
    resultado = percentiles.compute(_poblacion([2.0] * 5, LIGAS), (GOLES,), min_minutes=450)

    with pytest.raises(ValueError, match="inventada"):
        percentiles.for_player(resultado, "Jugador 0", "2526", basis="inventada")
