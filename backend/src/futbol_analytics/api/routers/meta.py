"""Endpoints de catalogo: que datos y que metricas hay disponibles.

Streamlit los usa para construir sus filtros sin hardcodear temporadas ni ligas,
y el chat los necesitara para saber sobre que puede preguntar.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from futbol_analytics.analysis.roles import ARCHETYPES
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import (
    Catalog,
    EtlRun,
    MetricInfo,
    PizzaTemplate,
    RoleInfo,
    TemplateSlice,
)
from futbol_analytics.config import get_settings
from futbol_analytics.metrics import PLAYER_METRICS
from futbol_analytics.templates import PIZZA_TEMPLATES

router = APIRouter(prefix="/meta", tags=["catalogo"])


@router.get("/catalog", summary="Temporadas y ligas disponibles")
def catalog(data: DataAccessDep) -> Catalog:
    return Catalog(
        seasons=data.seasons(),
        leagues=data.leagues(),
        min_minutes=get_settings().min_minutes,
    )


@router.get("/metrics", summary="Catalogo de metricas")
def metrics() -> list[MetricInfo]:
    """Las metricas que se pueden pedir, con como hay que leerlas.

    `higher_is_better` nulo significa que la metrica describe estilo y no
    calidad: la interfaz no debe pintarla como buena ni como mala.
    """
    return [
        MetricInfo(
            name=metric.name,
            label=metric.label,
            positions=list(metric.positions),
            higher_is_better=metric.higher_is_better,
            possession_sensitive=metric.possession_sensitive,
            team_dependent=metric.team_dependent,
        )
        for metric in PLAYER_METRICS
        if metric.per90
    ]


@router.get("/roles", summary="Roles que asigna el clustering")
def roles() -> list[RoleInfo]:
    return [
        RoleInfo(
            name=arquetipo.name,
            position_group=position_group,
            description=arquetipo.description,
        )
        for position_group, arquetipos in ARCHETYPES.items()
        for arquetipo in arquetipos
    ]


@router.get("/templates", summary="Ejes del pizza chart por posicion")
def templates() -> list[PizzaTemplate]:
    """Las metricas que se pintan para cada posicion, en orden.

    Son fijas a proposito: un selector libre de metricas haria que dos graficos
    del mismo jugador dejasen de ser comparables. Los porteros no aparecen porque
    las metricas de porteria disponibles no dan para un grafico legible.
    """
    etiquetas = {metric.name: metric.label for metric in PLAYER_METRICS}
    return [
        PizzaTemplate(
            position_group=position_group,
            slices=[
                TemplateSlice(
                    metric=porcion.metric,
                    label=etiquetas.get(porcion.metric, porcion.metric),
                    category=porcion.category,
                )
                for porcion in porciones
            ],
        )
        for position_group, porciones in PIZZA_TEMPLATES.items()
    ]


@router.get("/etl", summary="Ultimas ejecuciones del ETL")
def etl_runs(
    data: DataAccessDep,
    limit: int = Query(default=5, ge=1, le=50),
) -> list[EtlRun]:
    """Historial de cargas, de la mas reciente a la mas antigua.

    Sirve para responder a la pregunta que `data_version` no contesta: no solo
    de cuando son los datos, sino si el ultimo intento de actualizarlos salio
    bien. Con la carga programada esa diferencia importa, porque nadie mira los
    logs de un contenedor.
    """
    return [EtlRun(**fila) for fila in data.last_runs(limit)]
