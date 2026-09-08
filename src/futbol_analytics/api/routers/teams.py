"""Endpoints de equipos: estilo de juego."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status

from futbol_analytics.api import services
from futbol_analytics.api.dependencies import get_data_access
from futbol_analytics.api.repository import DataAccess
from futbol_analytics.api.schemas import StyleReport, TeamStyle

router = APIRouter(prefix="/teams", tags=["equipos"])


@router.get("/styles", summary="Estilos de juego de una temporada")
def styles(
    season: str,
    league: str | None = None,
    n_styles: int = Query(default=5, ge=2, le=10),
    data: DataAccess = Depends(get_data_access),
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
    return TeamStyle(
        league=fila["league"],
        season=fila["season"],
        team=fila["team"],
        style=fila["style"],
        cluster=int(fila["cluster"]),
        possession=_numero(fila.get("possession")),
        ppda=_numero(fila.get("ppda")),
        pressing_height=_numero(fila.get("pressing_height")),
    )


def _numero(valor: object) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)
