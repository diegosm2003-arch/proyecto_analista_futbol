"""Contratos de la API.

Son lo que consume Streamlit y, mas adelante, el chat. Llevan a proposito mas
contexto del estrictamente necesario para pintar: el tamano de la poblacion, la
base de comparacion usada y las advertencias de lectura. Un percentil sin esa
informacion se malinterpreta con facilidad, y el proyecto se juzga por si los
hallazgos son defendibles.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PositionGroup = Literal["GK", "DF", "MF", "FW"]
Basis = Literal["per90", "padj"]
Population = Literal["position", "role"]


class Health(BaseModel):
    """Estado del servicio."""

    status: str
    version: str
    data_version: str = Field(description="Marca de la ultima carga correcta del ETL")


class MetricInfo(BaseModel):
    """Descripcion de una metrica del catalogo."""

    name: str
    label: str
    positions: list[str]
    higher_is_better: bool | None = Field(
        description="Nulo cuando la metrica describe estilo y no calidad"
    )
    possession_sensitive: bool = Field(
        description="Si se ofrece tambien ajustada por posesion"
    )


class RoleInfo(BaseModel):
    """Un rol del catalogo de arquetipos."""

    name: str
    position_group: PositionGroup
    description: str


class TemplateSlice(BaseModel):
    """Una porcion del pizza chart."""

    metric: str
    label: str
    category: str


class PizzaTemplate(BaseModel):
    """Ejes fijos del grafico de una posicion.

    Se sirven desde la API para que la interfaz y el chat pinten siempre los
    mismos ejes: si cada cliente eligiera los suyos, dos graficos del mismo
    jugador dejarian de ser comparables.
    """

    position_group: PositionGroup
    slices: list[TemplateSlice]


class Catalog(BaseModel):
    """Que hay disponible en la plataforma."""

    seasons: list[str]
    leagues: list[str]
    min_minutes: int = Field(description="Umbral para entrar en la poblacion de comparacion")


class PlayerSummary(BaseModel):
    """Ficha minima de un jugador en una temporada."""

    league: str
    season: str
    team: str
    player: str
    position_group: PositionGroup | None
    detailed_position: str | None = Field(
        default=None, description="Rol asignado por el clustering; nulo si no es comparable"
    )
    minutes: int | None


class MetricPercentile(BaseModel):
    """Una metrica del perfil de un jugador."""

    metric: str
    label: str
    total: float | None = Field(description="Valor acumulado en la temporada")
    per90: float | None
    padj: float | None = Field(default=None, description="Ajustado por posesion del equipo")
    percentile: float | None = Field(description="0 a 100 dentro de su poblacion")
    higher_is_better: bool | None


class PlayerProfile(BaseModel):
    """Perfil completo, listo para un pizza chart."""

    player: PlayerSummary
    basis: Basis
    population: Population
    population_group: str | None = Field(description="Grupo contra el que se compara")
    population_size: int = Field(
        description="Jugadores en la poblacion. Por debajo de ~50 el percentil es fragil"
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Advertencias de lectura del perfil",
    )
    metrics: list[MetricPercentile]


class TeamStyle(BaseModel):
    """Estilo asignado a un equipo."""

    league: str
    season: str
    team: str
    style: str
    cluster: int
    possession: float | None
    ppda: float | None = Field(description="Aproximada: no comparable con otras fuentes")
    pressing_height: float | None = Field(description="Cuota de entradas en campo rival")


class StyleReport(BaseModel):
    """Resultado del clustering de estilos de una temporada."""

    season: str
    n_styles: int
    silhouette: float | None = Field(
        description="Calidad de la separacion. Bajo no invalida: el futbol es un continuo"
    )
    teams: list[TeamStyle]
