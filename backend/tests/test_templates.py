"""Tests de las plantillas del pizza chart.

Una plantilla que nombra una metrica inexistente produce un grafico con un eje
menos y sin error visible, asi que conviene atarlo aqui.
"""

from __future__ import annotations

import pytest

from futbol_analytics.metrics import PLAYER_METRICS, metrics_for_position
from futbol_analytics.templates import (
    CATEGORIES,
    NO_TEMPLATE,
    PIZZA_TEMPLATES,
    template_for,
)

NOMBRES = {metric.name: metric for metric in PLAYER_METRICS}


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_todas_las_metricas_de_la_plantilla_existen(position_group: str) -> None:
    for porcion in PIZZA_TEMPLATES[position_group]:
        assert porcion.metric in NOMBRES, f"{porcion.metric} no esta en el catalogo"


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_las_metricas_aplican_a_la_posicion(position_group: str) -> None:
    # Pintar paradas en el grafico de un lateral no es informacion, es ruido.
    relevantes = {m.name for m in metrics_for_position(PLAYER_METRICS, position_group)}

    for porcion in PIZZA_TEMPLATES[position_group]:
        assert porcion.metric in relevantes, f"{porcion.metric} no aplica a {position_group}"


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_las_metricas_se_pueden_normalizar_por_90(position_group: str) -> None:
    # Un total sin normalizar premiaria al que mas juega, no al mejor.
    for porcion in PIZZA_TEMPLATES[position_group]:
        assert NOMBRES[porcion.metric].per90, porcion.metric


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_ninguna_metrica_se_repite_en_la_plantilla(position_group: str) -> None:
    metricas = [porcion.metric for porcion in template_for(position_group)]

    assert len(metricas) == len(set(metricas))


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_el_grafico_es_legible(position_group: str) -> None:
    # Por encima de doce porciones las etiquetas dejan de caber; por debajo de
    # ocho el grafico no describe al jugador.
    assert 8 <= len(PIZZA_TEMPLATES[position_group]) <= 12


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_las_tres_categorias_estan_representadas(position_group: str) -> None:
    # Si falta una, el grafico deja de decir en que fase del juego aporta.
    categorias = {porcion.category for porcion in PIZZA_TEMPLATES[position_group]}

    assert categorias == set(CATEGORIES)


@pytest.mark.parametrize("position_group", sorted(PIZZA_TEMPLATES))
def test_las_porciones_van_agrupadas_por_categoria(position_group: str) -> None:
    # El grafico solo se lee de un vistazo si los colores forman bloques
    # continuos en lugar de alternarse.
    secuencia = [porcion.category for porcion in PIZZA_TEMPLATES[position_group]]
    bloques = [
        categoria
        for i, categoria in enumerate(secuencia)
        if i == 0 or secuencia[i - 1] != categoria
    ]

    assert len(bloques) == len(set(bloques))


def test_los_porteros_no_tienen_plantilla() -> None:
    # Solo se cargan tres metricas de porteria: una tabla dice mas que un
    # grafico de tres porciones.
    assert "GK" in NO_TEMPLATE
    assert template_for("GK") == ()


def test_una_posicion_desconocida_no_revienta() -> None:
    assert template_for(None) == ()
    assert template_for("XX") == ()
