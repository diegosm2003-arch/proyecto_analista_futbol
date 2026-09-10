"""Tests de la corrección por tamaño de muestra.

Lógica pura sobre DataFrames de ejemplo: no tocan la base de datos.
"""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import shrinkage


def _poblacion() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Mismo valor observado, minutos muy distintos.
            {
                "league": "L",
                "season": "2627",
                "position_group": "FW",
                "player": "Con muestra",
                "minutes": 2500,
                "np_xg": 1.0,
            },
            {
                "league": "L",
                "season": "2627",
                "position_group": "FW",
                "player": "Sin muestra",
                "minutes": 100,
                "np_xg": 1.0,
            },
            # El resto define la media del grupo.
            *[
                {
                    "league": "L",
                    "season": "2627",
                    "position_group": "FW",
                    "player": f"Medio {i}",
                    "minutes": 2000,
                    "np_xg": 0.2,
                }
                for i in range(8)
            ],
        ]
    )


def test_el_peso_es_medio_a_los_minutos_de_la_constante() -> None:
    # Es lo que hace que la constante se pueda leer y discutir en minutos de
    # juego en lugar de como un parametro abstracto.
    assert shrinkage.weight(750, 750) == pytest.approx(0.5)


def test_sin_minutos_no_pesa_nada_lo_observado() -> None:
    assert shrinkage.weight(0, 750) == 0.0


def test_a_igual_valor_el_de_pocos_minutos_se_contrae_mas() -> None:
    # Es el problema que esto resuelve: dos jugadores con el mismo numero no
    # merecen la misma confianza si uno lo ha hecho en 100 minutos.
    poblacion = _poblacion()
    ajustado = shrinkage.shrink(poblacion, "np_xg", "np_xg")

    con_muestra = ajustado[poblacion["player"] == "Con muestra"].iloc[0]
    sin_muestra = ajustado[poblacion["player"] == "Sin muestra"].iloc[0]

    assert con_muestra > sin_muestra
    # El de pocos minutos acaba mucho mas cerca de la media del grupo.
    assert sin_muestra < 0.6


def test_con_muchos_minutos_el_valor_apenas_se_toca() -> None:
    poblacion = _poblacion()
    ajustado = shrinkage.shrink(poblacion, "np_xg", "np_xg")

    con_muestra = ajustado[poblacion["player"] == "Con muestra"].iloc[0]

    assert con_muestra > 0.75


def test_se_contrae_hacia_la_media_del_grupo_y_no_de_la_liga() -> None:
    # La media a la que tiene sentido acercar a un central es la de los
    # centrales, no la de todos los futbolistas.
    mezcla = pd.DataFrame(
        [
            {
                "league": "L",
                "season": "2627",
                "position_group": "FW",
                "player": "Delantero",
                "minutes": 100,
                "np_xg": 0.5,
            },
            {
                "league": "L",
                "season": "2627",
                "position_group": "FW",
                "player": "Otro FW",
                "minutes": 2000,
                "np_xg": 0.5,
            },
            {
                "league": "L",
                "season": "2627",
                "position_group": "DF",
                "player": "Central",
                "minutes": 2000,
                "np_xg": 0.02,
            },
        ]
    )

    ajustado = shrinkage.shrink(mezcla, "np_xg", "np_xg")

    # El delantero se contrae hacia 0,5 (media de los FW), no hacia 0,34
    # (media de todos), asi que casi no se mueve.
    assert ajustado.iloc[0] == pytest.approx(0.5, abs=0.01)


def test_los_goles_estabilizan_mas_lento_que_los_tiros() -> None:
    # Es la decision futbolistica de fondo: los tiros ocurren varias veces por
    # partido y los goles son eventos raros. Aplicar la misma constante trataria
    # igual algo que se sabe en cuatro partidos y algo que no se sabe en
    # cuarenta.
    assert shrinkage.HALF_LIFE_MINUTES["shots"] < shrinkage.HALF_LIFE_MINUTES["np_goals"]
    assert shrinkage.reliability(500, "shots") > shrinkage.reliability(500, "np_goals")


def test_una_metrica_desconocida_se_contrae_de_mas_y_no_de_menos() -> None:
    # Ante lo que no se conoce, es mejor contraer de mas que afirmar de mas.
    assert shrinkage.HALF_LIFE_MINUTES["np_xg"] <= shrinkage.DEFAULT_HALF_LIFE


def test_las_lentas_se_pueden_listar_para_avisar_mas_fuerte() -> None:
    lentas = shrinkage.slowest_metrics()

    assert "np_goals" in lentas
    assert "shots" not in lentas


def test_una_poblacion_vacia_no_revienta() -> None:
    assert shrinkage.shrink(pd.DataFrame(), "np_xg", "np_xg").empty
