"""Endpoints de jugadores: busqueda y perfil de percentiles."""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from futbol_analytics.analysis import similarity
from futbol_analytics.api import services
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.repository import DataAccess
from futbol_analytics.api.schemas import (
    Basis,
    MetricPercentile,
    PlayerCard,
    PlayerMarket,
    PlayerProfile,
    PlayerSummary,
    Population,
    PositionGroup,
    SimilarPlayer,
    SimilarPlayers,
    Transfer,
    Valuation,
)
from futbol_analytics.metrics import PLAYER_METRICS, metrics_for_position
from futbol_analytics.templates import OUTFIELD_TEMPLATE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/players", tags=["jugadores"])

# Por debajo de este tamano de poblacion el percentil deja de ser fiable: con 30
# jugadores, cada posicion vale mas de tres puntos porcentuales.
FRAGILE_POPULATION = 50

# Las cinco grandes ligas europeas, que es la poblacion que el diseno asume.
EXPECTED_LEAGUES = 5


@router.get("", summary="Buscar jugadores")
def search(
    season: str,
    data: DataAccessDep,
    league: str | None = None,
    team: str | None = None,
    position_group: PositionGroup | None = None,
    role: str | None = None,
    name: str | None = Query(
        default=None, description="Busqueda parcial, sin distinguir mayusculas"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PlayerSummary]:
    """Lista de jugadores de una temporada, con su rol ya asignado."""
    jugadores = _players(data, season)

    if league:
        jugadores = jugadores[jugadores["league"] == league]
    if team:
        jugadores = jugadores[jugadores["team"] == team]
    if position_group:
        jugadores = jugadores[jugadores["position_group"] == position_group]
    if role:
        jugadores = jugadores[jugadores["detailed_position"] == role]
    if name:
        jugadores = jugadores[
            jugadores["player"].astype("string").str.contains(name, case=False, na=False)
        ]

    pagina = jugadores.sort_values("minutes", ascending=False).iloc[offset : offset + limit]
    return [_summary(fila) for _, fila in pagina.iterrows()]


@router.get("/{player}/profile", summary="Perfil de percentiles de un jugador")
def profile(
    player: str,
    season: str,
    data: DataAccessDep,
    team: str | None = Query(default=None, description="Necesario si cambio de equipo"),
    basis: Basis = "per90",
    population: Population = "position",
) -> PlayerProfile:
    """Percentiles de un jugador, listos para un pizza chart.

    El percentil se ha calculado contra toda la poblacion de las Big 5 de esa
    temporada; el filtro por jugador se aplica despues. Solo se devuelven las
    metricas que tienen sentido para su posicion: mostrar paradas en el perfil
    de un lateral no es informacion, es ruido.
    """
    todos = _percentiles(data, season, population)
    perfil = todos[(todos["player"] == player) & (todos["season"] == season)]
    if team:
        perfil = perfil[perfil["team"] == team]

    if perfil.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"{player!r} no aparece en la temporada {season!r}. Puede no estar cargado "
                "o no superar el umbral de minutos."
            ),
        )

    equipos = perfil["team"].unique()
    if len(equipos) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{player!r} tiene {len(equipos)} etapas en {season!r} ({', '.join(equipos)}). "
                "Indica el equipo: sus numeros en cada club son hechos distintos."
            ),
        )

    ficha = _summary(perfil.iloc[0])
    contexto = services.population_context(data, season)
    columna = services.population_column(population)
    grupo = perfil.iloc[0].get(columna)
    tamano = services.population_size(todos, season, columna, grupo)

    relevantes = {
        metric.name for metric in metrics_for_position(PLAYER_METRICS, ficha.position_group or "MF")
    }
    seleccion = perfil[perfil["metric"].isin(relevantes)]
    metricas = _metrics(seleccion, basis)

    avisos = _caveats(ficha, population, tamano, contexto)
    if basis == "padj" and all(metrica.percentile is None for metrica in metricas):
        # Pasa cuando no hay datos de equipo para su liga. El percentil ajustado
        # solo se calcula entre jugadores con posesion conocida, asi que si falta
        # no hay ajuste que mostrar.
        avisos.append(
            "No hay posesion de equipo para esta liga: el ajuste por posesion no "
            "esta disponible. Usa basis=per90."
        )

    return PlayerProfile(
        player=ficha,
        basis=basis,
        population=population,
        population_group=None if pd.isna(grupo) else grupo,
        population_size=tamano,
        population_leagues=contexto["leagues"],
        min_minutes_applied=contexto["min_minutes"],
        caveats=avisos,
        metrics=metricas,
    )


def _players(data: DataAccess, season: str) -> pd.DataFrame:
    try:
        return services.enriched_players(data, season)
    except services.NoDataError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


def _percentiles(data: DataAccess, season: str, population: str) -> pd.DataFrame:
    try:
        return services.player_percentiles(data, season, population)
    except services.NoDataError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/{player}/market", summary="Valor de mercado y carrera de un jugador")
def market(
    player: str,
    season: str,
    data: DataAccessDep,
    team: str | None = Query(default=None, description="Necesario si cambio de equipo"),
) -> PlayerMarket:
    """Ficha, curva de valor de mercado y carrera, segun Transfermarkt.

    Va aparte del perfil de percentiles a proposito: son dos fuentes distintas y
    una puede faltar sin que la otra deje de servir. Un jugador recien llegado a
    la liga tendra percentiles pero quiza no cruce con Transfermarkt todavia.

    Lo que anade es el contexto que a un percentil le falta. Un percentil 95 no
    significa lo mismo a los 19 anos que a los 33, ni en alguien a quien le
    queda un ano de contrato que en alguien atado hasta 2031.
    """
    jugadores = services.enriched_players(data, season)
    fila = jugadores[(jugadores["player"] == player) & (jugadores["season"] == season)]
    if team:
        fila = fila[fila["team"] == team]

    if fila.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{player!r} no aparece en la temporada {season!r}.",
        )
    if len(fila["team"].unique()) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"{player!r} tiene varias etapas en {season!r}. Indica el equipo."),
        )

    ficha = _summary(fila.iloc[0])
    understat_id = fila.iloc[0].get("understat_id")
    if not understat_id or pd.isna(understat_id):
        # Sin identificador estable no hay forma de cruzarlo con Transfermarkt.
        return PlayerMarket(
            player=ficha,
            card=None,
            current_value_eur=None,
            peak_value_eur=None,
            valuations=[],
            transfers=[],
            caveats=[
                "Este jugador no tiene identificador de Understat, asi que no se ha "
                "podido cruzar con Transfermarkt."
            ],
        )

    crudo = data.market(str(understat_id))
    tasaciones = [Valuation(**_solo(v, Valuation)) for v in crudo["market_value"]]
    valores = [t.market_value_eur for t in tasaciones if t.market_value_eur is not None]

    avisos = []
    if not tasaciones:
        avisos.append(
            "Sin valor de mercado cargado. El cruce con Transfermarkt puede estar "
            "pendiente de revision, o la carga aun no ha llegado a este jugador."
        )
    if tasaciones and valores and valores[-1] < max(valores):
        # Dato con lectura futbolistica: no es un fallo, es una carrera.
        avisos.append(
            f"Su valor actual esta por debajo de su maximo "
            f"({max(valores) / 1e6:.0f} M EUR). Suele indicar edad, lesiones o menos minutos."
        )

    return PlayerMarket(
        player=ficha,
        card=PlayerCard(**_solo(crudo["profile"], PlayerCard)) if crudo["profile"] else None,
        current_value_eur=valores[-1] if valores else None,
        peak_value_eur=max(valores) if valores else None,
        valuations=tasaciones,
        transfers=[Transfer(**_solo(t, Transfer)) for t in crudo["transfers"]],
        caveats=avisos,
    )


@router.get("/{player}/similar", summary="Jugadores con un perfil parecido")
def similar(
    player: str,
    season: str,
    data: DataAccessDep,
    team: str | None = Query(default=None, description="Necesario si cambio de equipo"),
    basis: Basis = "per90",
    limit: int = Query(default=similarity.DEFAULT_NEIGHBOURS, ge=1, le=20),
) -> SimilarPlayers:
    """Quien mas juega como el, dentro de su mismo grupo posicional.

    Es la pregunta con la que trabaja un scout: este futbolista me gusta, quien
    mas hace esto. No es un ranking de calidad ni una recomendacion: es un
    vecindario en el espacio de percentiles.

    Se compara **contra su propio grupo posicional** y con el mismo umbral de
    minutos que el resto de la plataforma, porque un perfil construido sobre
    noventa minutos no se parece a nada.
    """
    todos = _percentiles(data, season, "position")
    contexto = services.population_context(data, season)

    ficha = todos[(todos["player"] == player) & (todos["season"] == season)]
    if team:
        ficha = ficha[ficha["team"] == team]
    if ficha.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{player!r} no aparece en la temporada {season!r}.",
        )
    if len(ficha["team"].unique()) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{player!r} tiene varias etapas en {season!r}. Indica el equipo.",
        )

    resumen = _summary(ficha.iloc[0])
    resultado = similarity.nearest(
        todos,
        player=player,
        team=team or resumen.team,
        basis=basis,
        n=limit,
        min_minutes=contexto["min_minutes"],
        # Solo las metricas de aportacion. Las que no tienen direccion son los
        # denominadores y las tarjetas, y una metrica donde casi todos valen lo
        # mismo no separa a nadie: con las rojas dentro, media liga salia
        # "parecida en tarjetas rojas".
        metrics=[m.name for m in PLAYER_METRICS if m.higher_is_better is not None],
        families=_familias(),
    )

    vecinos = resultado.neighbours
    avisos = [
        "El parecido solo abarca lo que mide el catalogo, que hoy son metricas de "
        "ataque: dos defensas parecidos lo son con balon, no defendiendo."
    ]
    if not vecinos:
        avisos.append(
            "Sin jugadores comparables. Suele pasar con perfiles a los que les faltan "
            "metricas, o en posiciones con pocos jugadores por encima del umbral."
        )

    return SimilarPlayers(
        player=resumen,
        basis=basis,
        population_group=resumen.position_group,
        profile=resultado.profile,
        neighbours=[
            SimilarPlayer(
                league=v.league,
                team=v.team,
                player=v.player,
                minutes=v.minutes,
                similarity=v.similarity,
                closest=[_etiqueta(todos, m) for m in v.closest],
                furthest=[_etiqueta(todos, m) for m in v.furthest],
                profile=v.profile,
            )
            for v in vecinos
        ],
        caveats=avisos,
    )


def _familias() -> dict[str, list[str]]:
    """Metricas agrupadas por familia, segun la plantilla del grafico.

    Se toma de `templates` y no de una lista aparte para que el plano de
    scouting y el pizza chart hablen de lo mismo: seria confuso que el grafico
    dijera "finalizacion" refiriendose a unas metricas y el plano a otras.
    """
    familias: dict[str, list[str]] = {}
    for slice_ in OUTFIELD_TEMPLATE:
        familias.setdefault(slice_.category, []).append(slice_.metric)
    return familias


def _etiqueta(percentiles: pd.DataFrame, metrica: str) -> str:
    """Nombre legible de una metrica, para no devolver identificadores."""
    fila = percentiles[percentiles["metric"] == metrica]
    return str(fila.iloc[0]["label"]) if not fila.empty else metrica


def _solo(fila: dict, modelo: type[BaseModel]) -> dict:
    """Quita de una fila de base de datos lo que el modelo no declara.

    Las tablas llevan columnas de control (`scraped_at`, identificadores
    internos) que no pintan nada en una respuesta publica.
    """
    return {k: v for k, v in fila.items() if k in modelo.model_fields}


def _summary(fila: pd.Series) -> PlayerSummary:
    return PlayerSummary(
        league=fila["league"],
        season=fila["season"],
        team=fila["team"],
        player=fila["player"],
        position_group=_opcional(fila.get("position_group")),
        detailed_position=_opcional(fila.get("detailed_position")),
        minutes=None if pd.isna(fila.get("minutes")) else int(fila["minutes"]),
    )


def _metrics(perfil: pd.DataFrame, basis: Basis) -> list[MetricPercentile]:
    columna = f"percentile_{basis}"
    # El catalogo es quien sabe que metricas miden al equipo tanto como al
    # jugador; el perfil solo trae numeros.
    dependen_del_equipo = {m.name for m in PLAYER_METRICS if m.team_dependent}
    ordenado = perfil.sort_values(columna, ascending=False, na_position="last")
    return [
        MetricPercentile(
            metric=fila["metric"],
            label=fila["label"],
            total=_numero(fila.get("value")),
            per90=_numero(fila.get("per90")),
            padj=_numero(fila.get("padj")),
            percentile=_numero(fila.get(columna)),
            higher_is_better=_booleano(fila.get("higher_is_better")),
            team_dependent=fila["metric"] in dependen_del_equipo,
        )
        for _, fila in ordenado.iterrows()
    ]


def _caveats(
    ficha: PlayerSummary,
    population: str,
    tamano: int,
    contexto: dict[str, int],
) -> list[str]:
    """Advertencias de lectura que acompanan al perfil.

    Se devuelven desde la API y no desde la interfaz para que las vea tambien
    quien consuma los endpoints directamente, incluido el chat.
    """
    avisos = []
    if contexto["leagues"] < EXPECTED_LEAGUES:
        # El percentil solo significa lo que promete si la poblacion son las
        # Big 5. Con una liga cargada, un lateral se compara contra 80 laterales
        # en lugar de contra 400.
        avisos.append(
            f"La poblacion solo incluye {contexto['leagues']} de las "
            f"{EXPECTED_LEAGUES} grandes ligas: el percentil es menos solido de "
            "lo que el diseno pretende. Carga las Big 5 de esta temporada."
        )
    if contexto["min_minutes"] < contexto["configured_min_minutes"]:
        # Pasa en las primeras jornadas: el umbral baja para que la plataforma
        # no salga vacia, pero eso no hace fiables los ratios por 90.
        avisos.append(
            f"Temporada empezada: el umbral ha bajado a {contexto['min_minutes']} minutos "
            f"(configurado: {contexto['configured_min_minutes']}). Con tan pocos partidos, "
            "las metricas por 90 son muy inestables."
        )
    if tamano and tamano < FRAGILE_POPULATION:
        avisos.append(
            f"La poblacion de comparacion son solo {tamano} jugadores: el percentil es fragil."
        )
    if population == "position" and ficha.position_group == "DF":
        avisos.append(
            "El grupo DF mezcla centrales y laterales. Para una comparacion mas fina, "
            "pide population=role."
        )
    if ficha.detailed_position is None and ficha.position_group != "GK":
        avisos.append("Sin rol asignado: no ha superado el umbral de minutos.")
    return avisos


def _opcional(valor: object) -> str | None:
    return None if valor is None or pd.isna(valor) else str(valor)


def _numero(valor: object) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)


def _booleano(valor: object) -> bool | None:
    """Normaliza booleanos de numpy, que pydantic no acepta tal cual."""
    return None if valor is None or pd.isna(valor) else bool(valor)
