"""Contratos de la API.

Son lo que consume Streamlit y, mas adelante, el chat. Llevan a proposito mas
contexto del estrictamente necesario para pintar: el tamano de la poblacion, la
base de comparacion usada y las advertencias de lectura. Un percentil sin esa
informacion se malinterpreta con facilidad, y el proyecto se juzga por si los
hallazgos son defendibles.
"""

from __future__ import annotations

from datetime import date, datetime
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
    last_etl_status: str | None = Field(
        default=None,
        description=(
            "Estado del ultimo intento de carga: success, failed, running o stale. "
            "Puede ser 'failed' aunque data_version tenga fecha, si el ultimo "
            "intento no llego a terminar"
        ),
    )


class EtlRun(BaseModel):
    """Una ejecucion del ETL."""

    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    leagues: str
    seasons: str
    player_rows: int | None
    team_rows: int | None
    error: str | None


class MetricInfo(BaseModel):
    """Descripcion de una metrica del catalogo."""

    name: str
    label: str
    positions: list[str]
    higher_is_better: bool | None = Field(
        description="Nulo cuando la metrica describe estilo y no calidad"
    )
    possession_sensitive: bool = Field(description="Si se ofrece tambien ajustada por posesion")
    team_dependent: bool = Field(
        default=False, description="Si la metrica premia jugar en un equipo dominante"
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
    min_minutes: int = Field(description="Umbral configurado, con la temporada completa")
    min_minutes_applied: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Umbral que se aplica de verdad en cada temporada. Baja al principio, "
            "cuando nadie ha jugado lo suficiente para llegar al configurado"
        ),
    )


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
    team_dependent: bool = Field(
        default=False, description="Si la metrica premia jugar en un equipo dominante"
    )


class PlayerProfile(BaseModel):
    """Perfil completo, listo para un pizza chart."""

    player: PlayerSummary
    basis: Basis
    population: Population
    population_group: str | None = Field(description="Grupo contra el que se compara")
    population_size: int = Field(
        description="Jugadores en la poblacion. Por debajo de ~50 el percentil es fragil"
    )
    population_leagues: int = Field(
        description="Ligas cargadas en la poblacion. El diseno asume las 5 grandes"
    )
    min_minutes_applied: int = Field(
        description="Umbral de minutos usado. Baja solo si la temporada esta empezada"
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Advertencias de lectura del perfil",
    )
    metrics: list[MetricPercentile]


class PlayerCard(BaseModel):
    """Ficha de Transfermarkt: el contexto que un percentil no da."""

    age: int | None
    date_of_birth: date | None
    position: str | None = Field(
        default=None, description="Posicion concreta: Centre-Back, Left Winger..."
    )
    nationality: str | None
    height_cm: int | None
    foot: str | None
    joined_on: date | None
    signed_from: str | None
    contract_until: date | None


class Valuation(BaseModel):
    """Una tasacion en un momento de la carrera."""

    valuation_date: date
    market_value_eur: float | None
    club_at_time: str | None
    age_at_time: int | None


class Transfer(BaseModel):
    """Un movimiento de la carrera."""

    transfer_date: date
    club_from: str
    club_to: str
    fee_eur: float | None
    transfer_type: str | None = Field(
        default=None, description="traspaso, cesion o libre. Nulo si no consta el importe"
    )
    market_value_at_transfer_eur: float | None
    season: str | None


class PlayerMarket(BaseModel):
    """Valor de mercado y carrera de un jugador.

    Va aparte del perfil deportivo a proposito: son fuentes distintas y una
    puede faltar sin que la otra deje de servir.
    """

    player: PlayerSummary
    card: PlayerCard | None
    current_value_eur: float | None = Field(description="Ultima tasacion conocida")
    peak_value_eur: float | None = Field(description="Maximo historico")
    valuations: list[Valuation]
    transfers: list[Transfer]
    caveats: list[str] = Field(default_factory=list)


class SimilarPlayer(BaseModel):
    """Un jugador con perfil parecido."""

    league: str
    team: str
    player: str
    minutes: int | None
    similarity: float = Field(description="0 a 100. 100 seria un perfil identico")
    closest: list[str] = Field(description="Metricas en las que mas se parecen")
    furthest: list[str] = Field(description="Metricas en las que mas se separan")
    profile: dict[str, float] = Field(
        default_factory=dict,
        description="Percentil medio por familia: finalizacion, creacion y construccion",
    )


class SimilarPlayers(BaseModel):
    """Vecindario de un jugador dentro del espacio de percentiles."""

    player: PlayerSummary
    basis: Basis
    population_group: str | None = Field(description="Grupo dentro del que se ha buscado")
    profile: dict[str, float] = Field(
        default_factory=dict, description="Perfil por familias del jugador de referencia"
    )
    neighbours: list[SimilarPlayer]
    caveats: list[str] = Field(default_factory=list)


class SquadPlayer(BaseModel):
    """Un jugador de la plantilla, con lo que hace falta para planificar."""

    player: str
    age: int | None
    position: str | None
    market_value_eur: float | None


class TeamCard(BaseModel):
    """Un equipo tal y como se ensena en el navegador de la interfaz."""

    league: str
    season: str
    team: str
    squad_size: int = Field(description="Jugadores cargados de ese equipo")
    crest_url: str | None = Field(
        default=None, description="Escudo del club, si se ha cruzado con Transfermarkt"
    )
    market_value_eur: float | None = Field(default=None, description="Valor de plantilla")


class TeamStyle(BaseModel):
    """Estilo asignado a un equipo."""

    league: str
    season: str
    team: str
    style: str
    cluster: int
    ppda: float | None = Field(
        description="Pases del rival por accion defensiva. Mas bajo, mas presion"
    )
    territory: float | None = Field(
        description="Llegadas a zona de remate por partido: cuanto campo pisa de verdad"
    )
    chance_creation: float | None = Field(description="npxG generado por partido")
    chance_prevention: float | None = Field(description="npxG concedido por partido")


class StyleReport(BaseModel):
    """Resultado del clustering de estilos de una temporada."""

    season: str
    n_styles: int
    silhouette: float | None = Field(
        description="Calidad de la separacion. Bajo no invalida: el futbol es un continuo"
    )
    teams: list[TeamStyle]
