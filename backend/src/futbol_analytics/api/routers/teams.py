"""Endpoints de equipos: estilo de juego."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from futbol_analytics.api import services
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import (
    ConcededShots,
    Shot,
    SquadPlayer,
    StyleReport,
    TeamCard,
    TeamStyle,
)

router = APIRouter(prefix="/teams", tags=["equipos"])


@router.get("/styles", summary="Estilos de juego de una temporada")
def styles(
    season: str,
    data: DataAccessDep,
    league: str | None = None,
    n_styles: int = Query(default=5, ge=2, le=10),
) -> StyleReport:
    """Agrupa a los equipos por estilo de juego.

    Igual que con los percentiles, el clustering se hace sobre todas las ligas
    cargadas y el filtro por liga se aplica despues: un estilo de LaLiga solo
    significa algo comparado con el resto de Europa.
    """
    try:
        resultado = services.team_styles(data, season, n_styles)
    except services.NoDataError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    asignaciones = resultado.assignments
    if league:
        asignaciones = asignaciones[asignaciones["league"] == league]

    return StyleReport(
        season=season,
        n_styles=n_styles,
        silhouette=resultado.silhouette,
        teams=[_style(fila) for _, fila in asignaciones.iterrows()],
    )


# Patron del escudo en Transfermarkt. Se construye a partir del identificador
# en lugar de guardar la URL entera: es estable y evita una peticion por club
# solo para leer un campo que se puede derivar.
CREST_URL = "https://img.a.transfermarkt.technology/wappen/big/{club_id}.png"


@router.get("", summary="Equipos de una temporada, con escudo")
def teams(
    season: str,
    data: DataAccessDep,
    league: str | None = Query(default=None, description="Limitar a una liga"),
) -> list[TeamCard]:
    """Equipos cargados, para el navegador de la interfaz.

    Va aparte de `/teams/styles` porque responde a otra pregunta: aquello dice
    como juega cada equipo, y esto solo dice cuales hay. Se usa para elegir, no
    para analizar, y por eso no arrastra el coste del clustering.
    """
    jugadores = services.enriched_players(data, season)
    if league:
        jugadores = jugadores[jugadores["league"] == league]
    if jugadores.empty:
        return []

    identidades = data.team_identities(season)
    plantillas = jugadores.groupby(["league", "team"]).size()

    fichas = []
    for (liga, equipo), tamano in plantillas.items():
        identidad = identidades.get((liga, equipo), {})
        club_id = identidad.get("transfermarkt_id")
        fichas.append(
            TeamCard(
                league=liga,
                season=season,
                team=equipo,
                squad_size=int(tamano),
                crest_url=CREST_URL.format(club_id=club_id) if club_id else None,
            )
        )
    return sorted(fichas, key=lambda f: (f.league, f.team))


@router.get("/{team}/squad", summary="Plantilla con edad y valor")
def squad(
    team: str,
    season: str,
    league: str,
    data: DataAccessDep,
) -> list[SquadPlayer]:
    """Edad y valor de cada jugador de un equipo.

    Es lo que sostiene la lectura de planificacion: si el patrimonio del club
    esta en gente que aun va a subir o en gente que ya solo puede bajar.
    """
    return [SquadPlayer(**fila) for fila in data.squad_market(season, league, team)]


@router.get("/{team}/shots-conceded", summary="Tiros que recibe un equipo")
def shots_conceded(team: str, season: str, data: DataAccessDep) -> ConcededShots:
    """Desde dónde le rematan a un equipo.

    Con esta fuente no hay entradas ni intercepciones, así que no se puede medir
    la acción defensiva. Sí se puede medir su resultado: cuántos remates permite
    un equipo, desde dónde y de qué calidad. Un bloque bajo que concede muchos
    disparos lejanos y un bloque alto que concede pocos pero claros son estilos
    opuestos que el total de goles encajados confunde en una sola cifra.
    """
    crudos = data.shots_conceded(season, team)
    tiros = [Shot(**_solo_tiro(t)) for t in crudos]
    sin_penalti = [t for t in tiros if t.situation != "Penalty"]
    xg_sin_penalti = sum(t.xg or 0.0 for t in sin_penalti)

    avisos = []
    if not tiros:
        avisos.append("Sin tiros cargados para este equipo. Lanza el ETL con `--only shots`.")
    else:
        avisos.append(
            "Esto mide lo que un equipo permite, no cómo defiende: Understat no publica "
            "entradas ni intercepciones. Conceder pocos remates puede venir de defender "
            "bien o de tener el balón todo el partido."
        )

    return ConcededShots(
        team=team,
        season=season,
        matches=len({t.get("game_id") for t in crudos if t.get("game_id")}),
        shots=tiros,
        xg_conceded=round(sum(t.xg or 0.0 for t in tiros), 3),
        goals_conceded=sum(1 for t in tiros if t.result == "Goal"),
        xg_per_shot=(round(xg_sin_penalti / len(sin_penalti), 3) if sin_penalti else None),
        caveats=avisos,
    )


def _solo_tiro(fila: dict) -> dict:
    """Quita de la fila lo que el modelo publico no declara."""
    return {k: v for k, v in fila.items() if k in Shot.model_fields}


def _style(fila: pd.Series) -> TeamStyle:
    """Un equipo con su estilo y los rasgos que lo situan en el mapa.

    Los nombres vienen del clustering, que es quien sabe que se puede medir con
    esta fuente. Antes se pedian `possession` y `pressing_height`, que eran
    conceptos de FBref: al cambiar a Understat esas columnas dejaron de existir,
    la API devolvia nulos y el mapa de estilos no se ha podido dibujar desde
    entonces, sin ningun error de por medio.

    La PPDA se deshace la inversion que el clustering le aplica para poder
    ensenarla como se publica: un numero que va en un eje tiene que leerse igual
    que en cualquier otra fuente.
    """
    presion = _numero(fila.get("pressing"))
    return TeamStyle(
        league=fila["league"],
        season=fila["season"],
        team=fila["team"],
        style=fila["style"],
        cluster=int(fila["cluster"]),
        ppda=None if presion is None else -presion,
        territory=_numero(fila.get("territory")),
        chance_creation=_numero(fila.get("chance_creation")),
        chance_prevention=_numero(fila.get("chance_prevention")),
    )


def _numero(valor: object) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)
