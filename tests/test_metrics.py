"""Tests del catalogo de metricas.

El catalogo es la fuente de verdad del esquema, asi que una incoherencia aqui se
propaga a la base de datos. Estos tests son baratos y evitan justo eso.
"""

from __future__ import annotations

import pytest

from futbol_analytics.metrics import (
    ALL_POSITIONS,
    PLAYER_METRICS,
    TEAM_METRICS,
    Metric,
    metrics_by_stat_type,
    metrics_for_position,
    stat_types,
)

CATALOGOS = {"jugadores": PLAYER_METRICS, "equipos": TEAM_METRICS}


@pytest.mark.parametrize("catalogo", CATALOGOS.values(), ids=CATALOGOS.keys())
def test_los_nombres_canonicos_son_unicos(catalogo: tuple[Metric, ...]) -> None:
    # Un nombre repetido se traduciria en dos columnas con el mismo nombre.
    nombres = [metric.name for metric in catalogo]
    assert len(nombres) == len(set(nombres))


@pytest.mark.parametrize("catalogo", CATALOGOS.values(), ids=CATALOGOS.keys())
def test_no_hay_dos_metricas_leyendo_la_misma_columna(catalogo: tuple[Metric, ...]) -> None:
    origenes = [(metric.stat_type, metric.column) for metric in catalogo]
    assert len(origenes) == len(set(origenes))


@pytest.mark.parametrize("catalogo", CATALOGOS.values(), ids=CATALOGOS.keys())
def test_las_posiciones_declaradas_existen(catalogo: tuple[Metric, ...]) -> None:
    for metric in catalogo:
        assert metric.positions, f"{metric.name} no aplica a ninguna posicion"
        assert set(metric.positions) <= set(ALL_POSITIONS), metric.name


def test_ninguna_metrica_guarda_valores_ya_normalizados_por_90() -> None:
    # Regla de diseno: se persisten totales. El per-90 se calcula en la capa de
    # analisis, donde se conocen el umbral de minutos y la poblacion.
    for metric in PLAYER_METRICS:
        assert not metric.column.startswith("per_90_minutes"), metric.name


def test_los_minutos_estan_en_el_catalogo_y_no_se_normalizan() -> None:
    # Sin minutos no hay per-90 ni umbral de muestra: es la metrica que sostiene
    # todo el resto del analisis.
    minutos = next(metric for metric in PLAYER_METRICS if metric.name == "minutes")
    assert minutos.per90 is False
    assert minutos.dtype == "int"


def test_stat_types_no_repite_y_cubre_el_catalogo() -> None:
    tipos = stat_types(PLAYER_METRICS)

    assert len(tipos) == len(set(tipos))
    assert set(tipos) == {metric.stat_type for metric in PLAYER_METRICS}


def test_metrics_by_stat_type_filtra_por_origen() -> None:
    defensa = metrics_by_stat_type(PLAYER_METRICS, "defense")

    assert defensa
    assert {metric.stat_type for metric in defensa} == {"defense"}


def test_los_porteros_tienen_metricas_propias_y_no_las_de_campo() -> None:
    porteros = {metric.name for metric in metrics_for_position(PLAYER_METRICS, "GK")}

    # Paradas y goles encajados solo tienen sentido para un portero.
    assert {"saves", "goals_against"} <= porteros
    # Comparar a un portero por goles o regates no dice nada del juego.
    assert "goals" not in porteros
    assert "take_ons_successful" not in porteros


def test_las_metricas_de_estilo_no_se_marcan_como_buenas_ni_malas() -> None:
    # Las entradas por tercio describen la altura de la presion. Que un equipo
    # entre mucho en su propio tercio no es peor: es otra forma de defender.
    for nombre in ("tackles_def_third", "tackles_att_third", "clearances"):
        metric = next(m for m in PLAYER_METRICS if m.name == nombre)
        assert metric.higher_is_better is None, nombre
