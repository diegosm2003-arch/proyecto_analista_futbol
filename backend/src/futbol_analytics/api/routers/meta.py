"""Endpoints de catalogo: que datos y que metricas hay disponibles.

Streamlit los usa para construir sus filtros sin hardcodear temporadas ni ligas,
y el chat los necesitara para saber sobre que puede preguntar.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from futbol_analytics.analysis import insights
from futbol_analytics.analysis.roles import ARCHETYPES
from futbol_analytics.api import services
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import (
    Catalog,
    EtlRun,
    Insight,
    MetricInfo,
    PizzaTemplate,
    RoleInfo,
    TemplateSlice,
)
from futbol_analytics.config import get_settings
from futbol_analytics.metrics import PLAYER_METRICS
from futbol_analytics.templates import OUTFIELD_TEMPLATE, PIZZA_TEMPLATES

router = APIRouter(prefix="/meta", tags=["catalogo"])


@router.get("/catalog", summary="Temporadas y ligas disponibles")
def catalog(data: DataAccessDep) -> Catalog:
    """Que hay cargado y con que umbral se compara.

    El umbral se publica por temporada y no solo el configurado porque no son lo
    mismo cuando la temporada acaba de empezar: en la jornada 4 nadie llega a
    450 minutos, asi que baja para que la plataforma no salga vacia. La interfaz
    anunciaba el configurado y decia "solo entran los jugadores con al menos 450
    minutos" mientras comparaba a partir de 135.
    """
    temporadas = data.seasons()
    return Catalog(
        seasons=temporadas,
        leagues=data.leagues(),
        min_minutes=get_settings().min_minutes,
        min_minutes_applied={
            temporada: services.population_context(data, temporada)["min_minutes"]
            for temporada in temporadas
        },
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


@router.get("/insights", summary="Lo que dicen los datos cargados")
def insights_endpoint(season: str, data: DataAccessDep) -> list[Insight]:
    """Hallazgos de la temporada, cada uno con su matiz de lectura.

    Es lo que da la bienvenida en lugar de un recuento de ligas cargadas. El
    criterio de valor del proyecto no es tecnico: un analisis vale si se puede
    resumir en una frase que a un aficionado avanzado le resulte interesante, y
    una portada es justo donde eso tiene que demostrarse.

    Los hallazgos que no se pueden calcular con lo que hay cargado se omiten en
    lugar de devolverse vacios: media portada con huecos es peor que media
    portada con tres frases buenas.
    """
    jugadores = services.enriched_players(data, season)
    percentiles = services.player_percentiles(data, season)

    # La edad vive en la ficha de Transfermarkt, no en `player_season`, asi que
    # se pega aqui y no se arrastra en el frame que usa el resto de la API.
    edades = data.ages(season)
    if not jugadores.empty and "understat_id" in jugadores.columns:
        jugadores = jugadores.assign(age=jugadores["understat_id"].map(edades))

    familias: dict[str, list[str]] = {}
    for slice_ in OUTFIELD_TEMPLATE:
        familias.setdefault(slice_.category, []).append(slice_.metric)

    hallazgos = [
        insights.overperformer(jugadores),
        insights.young_standout(
            jugadores,
            percentiles,
            # Solo lo que mide aportacion: sin este filtro salia un chaval
            # "destacado" en el percentil 94 de tarjetas amarillas.
            metrics=[m.name for m in PLAYER_METRICS if m.higher_is_better is not None],
        ),
        insights.sharpest_contrast(percentiles, familias),
        insights.territorial_team(data.teams(season)),
    ]
    return [
        Insight(
            topic=h.topic,
            headline=h.headline,
            subject=h.subject,
            detail=h.detail,
            caveat=h.caveat,
        )
        for h in hallazgos
        if h is not None
    ]
