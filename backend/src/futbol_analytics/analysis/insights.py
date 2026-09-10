"""Hallazgos: lo que los datos cargados tienen de interesante hoy.

Existe por el criterio de valor del proyecto, que no es tecnico: un analisis
vale si se puede resumir en una frase que a un aficionado avanzado le resulte
interesante. Una portada que enumera cuantas ligas hay cargadas no cumple eso;
una que dice quien esta marcando cuarenta puntos por encima de su xG, si.

**Cada hallazgo lleva su matiz.** No es adorno: casi todos los extremos de una
temporada empezada son ruido, y presentarlos sin decirlo convierte una
herramienta de analisis en una maquina de titulares. El matiz es lo que separa
"Fulano marca por encima de lo esperado" de "Fulano lleva una racha que las
series largas suelen corregir".

**Se calculan sobre lo que ya esta en memoria.** Reutilizan el frame de
percentiles que la API ya cachea para todo lo demas, asi que la portada no
anade una consulta pesada a la base.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

# Percentil desde el que un valor se considera destacable. El mismo corte que
# usa el aviso de metricas extremas, para que la plataforma hable con un solo
# criterio.
HIGH_PERCENTILE = 90.0

# Edad hasta la que un jugador cuenta como joven a efectos de mercado. No es un
# limite fisico sino de valor: es donde Transfermarkt y los clubes situan la
# frontera entre promesa y futbolista hecho.
YOUNG_AGE = 21


@dataclass(frozen=True, slots=True)
class Insight:
    """Un hallazgo, con su lectura."""

    # Que pregunta responde. Sirve de titulillo.
    topic: str
    # La frase. Debe poder leerse sola.
    headline: str
    # El sujeto: jugador o equipo.
    subject: str
    detail: str
    # Como hay que leerlo. Vacio solo si de verdad no hay nada que matizar.
    caveat: str = ""


def _pivot(percentiles: pd.DataFrame, basis: str = "per90") -> pd.DataFrame:
    """Una fila por jugador con sus percentiles en columnas."""
    columna = f"percentile_{basis}"
    if percentiles.empty or columna not in percentiles.columns:
        return pd.DataFrame()
    return percentiles.pivot_table(
        index=["league", "season", "team", "player"],
        columns="metric",
        values=columna,
        aggfunc="first",
    )


def overperformer(players: pd.DataFrame) -> Insight | None:
    """Quien mas esta marcando por encima de sus ocasiones.

    Es el hallazgo mas llamativo de cualquier temporada y el mas malinterpretado:
    la diferencia entre goles y xG se corrige sola en cuanto hay muestra, asi
    que describe una racha y no una habilidad.
    """
    if players.empty or not {"np_goals", "np_xg"}.issubset(players.columns):
        return None

    marco = players.copy()
    goles = pd.to_numeric(marco["np_goals"], errors="coerce")
    xg = pd.to_numeric(marco["np_xg"], errors="coerce")
    # Un umbral de xG evita que gane siempre alguien con un gol y 0,1 de xG.
    marco = marco[xg >= 1.0]
    if marco.empty:
        return None

    marco["diferencia"] = goles - xg
    mejor = marco.loc[marco["diferencia"].idxmax()]
    if pd.isna(mejor["diferencia"]) or mejor["diferencia"] <= 0:
        return None

    return Insight(
        topic="Acierto",
        headline=(
            f"{mejor['player']} lleva {mejor['diferencia']:.1f} goles más de los que "
            "dicen sus ocasiones"
        ),
        subject=f"{mejor['player']} ({mejor['team']})",
        detail=(
            f"{int(mejor['np_goals'])} goles sin penalti para {float(mejor['np_xg']):.1f} de xG."
        ),
        caveat=(
            "La diferencia entre goles y xG se corrige sola en cuanto hay partidos: "
            "describe una racha, no una habilidad."
        ),
    )


def young_standout(
    players: pd.DataFrame,
    percentiles: pd.DataFrame,
    metrics: Sequence[str] | None = None,
) -> Insight | None:
    """El jugador mas joven que ya esta en el percentil alto de algo.

    Es la pregunta con la que trabaja una direccion deportiva: quien esta
    rindiendo como un futbolista hecho sin serlo todavia.

    `metrics` acota a las metricas de aportacion. Sin ese filtro salia un
    canterano de 18 anos "destacado en el percentil 94 de tarjetas amarillas",
    que no es una promesa sino un chaval al que amonestan mucho: las tarjetas
    describen como compite, no lo que aporta.
    """
    ancho = _pivot(percentiles)
    if ancho.empty or "age" not in players.columns:
        return None

    if metrics is not None:
        columnas = [c for c in ancho.columns if c in set(metrics)]
        if not columnas:
            return None
        ancho = ancho[columnas]

    edades = players.dropna(subset=["age"])
    edades = edades[pd.to_numeric(edades["age"], errors="coerce") <= YOUNG_AGE]
    if edades.empty:
        return None

    maximos = ancho.max(axis=1)
    destacados = maximos[maximos >= HIGH_PERCENTILE]
    if destacados.empty:
        return None

    candidatos = edades.set_index(["league", "season", "team", "player"])
    comunes = candidatos.index.intersection(destacados.index)
    if comunes.empty:
        return None

    elegido = candidatos.loc[comunes].sort_values("age").iloc[0]
    clave = candidatos.loc[comunes].sort_values("age").index[0]
    metrica = ancho.loc[clave].idxmax()
    etiqueta = _etiqueta(percentiles, metrica)

    return Insight(
        topic="Promesas",
        headline=(
            f"{clave[3]}, con {int(elegido['age'])} años, ya está en el percentil "
            f"{int(destacados[clave])} de {etiqueta.lower()}"
        ),
        subject=f"{clave[3]} ({clave[2]})",
        detail="Comparado con los jugadores de su posición en las cinco grandes ligas.",
        caveat=(
            "Un percentil alto con pocos minutos es frágil: conviene mirar cuanto ha "
            "jugado antes de sacar conclusiones."
        ),
    )


def sharpest_contrast(percentiles: pd.DataFrame, families: dict[str, list[str]]) -> Insight | None:
    """El perfil mas desequilibrado: excelente en una faceta y flojo en otra.

    Interesa porque es donde el percentil cuenta algo que una tabla no cuenta.
    Un jugador con 99 en construccion y 15 en finalizacion no es "bueno" ni
    "malo": es un tipo concreto de futbolista.
    """
    ancho = _pivot(percentiles)
    if ancho.empty or len(families) < 2:
        return None

    medias = pd.DataFrame(
        {
            familia: ancho[[m for m in metricas if m in ancho.columns]].mean(axis=1)
            for familia, metricas in families.items()
        }
    ).dropna()
    if medias.empty:
        return None

    rango = medias.max(axis=1) - medias.min(axis=1)
    clave = rango.idxmax()
    fila = medias.loc[clave]

    return Insight(
        topic="Perfiles extremos",
        headline=(
            f"{clave[3]} es el perfil más desequilibrado: percentil "
            f"{int(fila.max())} en {fila.idxmax().lower()} y {int(fila.min())} en "
            f"{fila.idxmin().lower()}"
        ),
        subject=f"{clave[3]} ({clave[2]})",
        detail="Un contraste así describe un tipo de fútbolista, no lo bueno que es.",
        caveat="",
    )


def territorial_team(teams: pd.DataFrame) -> Insight | None:
    """El equipo que mas pisa la zona de remate rival."""
    if teams.empty or "deep_completions" not in teams.columns:
        return None

    a_favor = teams[teams["perspective"] == "for"].copy()
    partidos = pd.to_numeric(a_favor["matches_played"], errors="coerce")
    llegadas = pd.to_numeric(a_favor["deep_completions"], errors="coerce")
    a_favor["por_partido"] = llegadas / partidos.where(partidos > 0)
    a_favor = a_favor.dropna(subset=["por_partido"])
    if a_favor.empty:
        return None

    mejor = a_favor.loc[a_favor["por_partido"].idxmax()]
    return Insight(
        topic="Territorio",
        headline=(
            f"{mejor['team']} llega {mejor['por_partido']:.1f} veces por partido a zona "
            "de remate, más que nadie"
        ),
        subject=f"{mejor['team']} ({mejor['league']})",
        detail="Pisar el área no es lo mismo que tener el balón, y separa mejor los estilos.",
        caveat="",
    )


def _etiqueta(percentiles: pd.DataFrame, metrica: str) -> str:
    fila = percentiles[percentiles["metric"] == metrica]
    return str(fila.iloc[0]["label"]) if not fila.empty else metrica
