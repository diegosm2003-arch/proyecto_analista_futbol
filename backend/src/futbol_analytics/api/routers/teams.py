"""Endpoints de equipos: estilo de juego."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from futbol_analytics.api import services
from futbol_analytics.api.dependencies import DataAccessDep
from futbol_analytics.api.schemas import StyleReport, TeamStyle

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
