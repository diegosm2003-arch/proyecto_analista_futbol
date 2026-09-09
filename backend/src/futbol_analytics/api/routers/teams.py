"""Endpoints de equipos: estilo de juego."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from futbol_analytics.api import services
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import SquadPlayer, StyleReport, TeamCard, TeamStyle

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
