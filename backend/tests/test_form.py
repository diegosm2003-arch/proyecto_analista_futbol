"""Tests de la trayectoria y la forma reciente.

Lógica pura sobre DataFrames de ejemplo: no tocan la base de datos.
"""

from __future__ import annotations

import pandas as pd

from futbol_analytics.analysis import form


def _partidos(goles: list[int], xg: list[float], minutos: list[int] | None = None) -> pd.DataFrame:
    minutos = minutos or [90] * len(goles)
    return pd.DataFrame(
        {
            "match_label": [f"2026-08-{10 + i:02d} A-B" for i in range(len(goles))],
            "position": ["FW"] * len(goles),
            "minutes": minutos,
            "goals": goles,
            "xg": xg,
            "assists": [0] * len(goles),
            "xa": [0.0] * len(goles),
        }
    )


def test_la_curva_acumulada_crece_partido_a_partido() -> None:
    puntos = form.trajectory(_partidos([1, 0, 2], [0.5, 0.4, 0.9]))

    assert [p.cumulative_goals for p in puntos] == [1, 1, 3]
    assert [p.cumulative_xg for p in puntos] == [0.5, 0.9, 1.8]


def test_el_orden_lo_da_la_fecha_y_no_el_orden_de_llegada() -> None:
    # La curva acumulada no significa nada si los partidos vienen desordenados.
    desordenados = _partidos([1, 0, 2], [0.5, 0.4, 0.9]).iloc[::-1]

    puntos = form.trajectory(desordenados)

    assert [p.cumulative_goals for p in puntos] == [1, 1, 3]


def test_la_forma_compara_con_la_media_del_propio_jugador() -> None:
    # Cinco partidos flojos y cinco buenos: la ventana reciente tiene que salir
    # por encima de la media de la temporada.
    partidos = _partidos([0] * 5 + [1] * 5, [0.1] * 5 + [0.8] * 5)

    resumen = form.form(partidos, window=5)

    assert resumen.recent_xg90 > resumen.season_xg90
    assert resumen.delta > 0


def test_con_pocos_partidos_se_avisa_en_lugar_de_afirmar() -> None:
    # Con tres partidos, cualquier diferencia entra dentro de lo esperable.
    resumen = form.form(_partidos([1, 0, 1], [0.4, 0.2, 0.6]))

    assert resumen.caveat


def test_sin_minutos_no_se_inventa_un_por_90() -> None:
    # Un jugador que solo ha entrado en el descuento no tiene un xG por 90:
    # tiene ruido dividido por un número pequeño.
    resumen = form.form(_partidos([0, 0], [0.0, 0.0], minutos=[0, 0]))

    assert resumen.season_xg90 is None
    assert resumen.delta is None


def test_sin_partidos_no_revienta() -> None:
    vacio = pd.DataFrame()

    assert form.trajectory(vacio) == []
    assert form.form(vacio).matches == 0
