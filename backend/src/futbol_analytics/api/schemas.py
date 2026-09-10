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
    data_version: str = Field(description="Marca de la última carga correcta del ETL")
    last_etl_status: str | None = Field(
        default=None,
        description=(
            "Estado del último intento de carga: success, failed, running o stale. "
            "Puede ser 'failed' aunque data_version tenga fecha, si el último "
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
        description="Nulo cuando la métrica describe estilo y no calidad"
    )
    possession_sensitive: bool = Field(description="Si se ofrece también ajustada por posesión")
    team_dependent: bool = Field(
        default=False, description="Si la métrica premia jugar en un equipo dominante"
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
    padj: float | None = Field(default=None, description="Ajustado por posesión del equipo")
    percentile: float | None = Field(description="0 a 100 dentro de su población")
    higher_is_better: bool | None
    team_dependent: bool = Field(
        default=False, description="Si la métrica premia jugar en un equipo dominante"
    )


class PlayerProfile(BaseModel):
    """Perfil completo, listo para un pizza chart."""

    player: PlayerSummary
    basis: Basis
    population: Population
    population_group: str | None = Field(description="Grupo contra el que se compara")
    population_size: int = Field(
        description="Jugadores en la población. Por debajo de ~50 el percentil es frágil"
    )
    population_leagues: int = Field(
        description="Ligas cargadas en la población. El diseño asume las 5 grandes"
    )
    min_minutes_applied: int = Field(
        description="Umbral de minutos usado. Baja solo si la temporada esta empezada"
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Advertencias de lectura del perfil",
    )
    metrics: list[MetricPercentile]


class Insight(BaseModel):
    """Un hallazgo de la temporada cargada, con su lectura."""

    topic: str = Field(description="Que pregunta responde")
    headline: str = Field(description="La frase, legible sola")
    subject: str
    detail: str
    caveat: str = Field(default="", description="Como hay que leerlo")


class Shot(BaseModel):
    """Un tiro, con donde se hizo y cuanto valia."""

    minute: int | None
    xg: float | None = Field(description="xG de ESTE tiro, no acumulado")
    location_x: float | None = Field(description="0 a 1; 1 es la linea de gol rival")
    location_y: float | None = Field(description="0 a 1 de banda a banda")
    body_part: str | None
    situation: str | None = Field(
        default=None, description="Open Play, From Corner, Set Piece, Direct Freekick o Penalty"
    )
    result: str | None
    match_date: date | None


class ShotMap(BaseModel):
    """Todos los tiros de un jugador en una temporada."""

    player: PlayerSummary
    shots: list[Shot]
    total_xg: float = Field(description="Suma del xG de todos los tiros")
    np_xg: float = Field(description="Lo mismo sin penaltis")
    goals: int
    xg_per_shot: float | None = Field(
        default=None, description="Calidad media de ocasion, sin penaltis"
    )
    caveats: list[str] = Field(default_factory=list)


class MatchPoint(BaseModel):
    """Un partido dentro de la trayectoria de la temporada."""

    match_label: str | None
    position: str | None = Field(
        default=None, description="La que jugo ESE dia, no la de la temporada"
    )
    minutes: int
    goals: int
    xg: float
    assists: int
    xa: float
    cumulative_goals: int
    cumulative_xg: float


class PlayerForm(BaseModel):
    """Como va la temporada y como esta ahora, que son preguntas distintas."""

    player: PlayerSummary
    matches: list[MatchPoint]
    played: int
    recent_matches: int
    recent_xg90: float | None
    season_xg90: float | None
    delta_xg90: float | None = Field(
        default=None, description="Cuanto se separa la ventana reciente de su media"
    )
    caveats: list[str] = Field(default_factory=list)


class ScoutingHit(BaseModel):
    """Un jugador que cumple los criterios de busqueda."""

    league: str
    team: str
    player: str
    position_group: PositionGroup | None
    minutes: int | None
    age: int | None
    contract_until: date | None
    months_left: int | None = Field(default=None, description="Meses hasta el fin de contrato")
    market_value_eur: float | None
    metric: str
    label: str
    percentile: float


class ScoutingResult(BaseModel):
    """Resultado del buscador de scouting."""

    season: str
    metric: str
    hits: list[ScoutingHit]
    caveats: list[str] = Field(default_factory=list)


class PlayerCard(BaseModel):
    """Ficha de Transfermarkt: el contexto que un percentil no da."""

    age: int | None
    date_of_birth: date | None
    position: str | None = Field(
        default=None, description="Posición concreta: Centre-Back, Left Winger..."
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
    current_value_eur: float | None = Field(description="Ultima tasación conocida")
    peak_value_eur: float | None = Field(description="Máximo histórico")
    valuations: list[Valuation]
    transfers: list[Transfer]
    caveats: list[str] = Field(default_factory=list)


class SimilarPlayer(BaseModel):
    """Un jugador con perfil parecido."""

    league: str
    team: str
    player: str
    minutes: int | None
    similarity: float = Field(description="0 a 100. 100 sería un perfil idéntico")
    closest: list[str] = Field(description="Métricas en las que más se parecen")
    furthest: list[str] = Field(description="Métricas en las que más se separan")
    profile: dict[str, float] = Field(
        default_factory=dict,
        description="Percentil medio por familia: finalización, creación y construcción",
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


class ConcededShots(BaseModel):
    """Lo que le rematan a un equipo, y desde donde.

    Es lo mas cerca que se puede estar de medir defensa con esta fuente:
    Understat no publica entradas ni intercepciones, pero si donde le tiran a
    cada equipo, que dice mucho de como defiende.
    """

    team: str
    season: str
    matches: int = Field(description="Partidos con tiros cargados")
    shots: list[Shot]
    xg_conceded: float
    goals_conceded: int
    xg_per_shot: float | None = Field(
        default=None, description="Calidad media de lo que concede, sin penaltis"
    )
    caveats: list[str] = Field(default_factory=list)


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
        description="Pases del rival por accion defensiva. Mas bajo, más presión"
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
        description="Calidad de la separación. Bajo no invalida: el fútbol es un continuo"
    )
    teams: list[TeamStyle]
