"""Forma y trayectoria dentro de una temporada.

Con datos agregados por temporada solo se puede responder *cómo va la
temporada*. Con datos por partido se puede responder también *cómo está ahora*,
que es una pregunta distinta y a menudo la que importa: un delantero con seis
goles en veinte partidos y otro con seis en los últimos cuatro tienen el mismo
número y no están en el mismo momento.

**Lo acumulado antes que la media móvil.** Con cuatro o cinco jornadas, una
media móvil de tres partidos es prácticamente el dato bruto con otro nombre:
suaviza sobre una ventana que no tiene suficientes puntos y sugiere una
tendencia donde solo hay ruido. La curva acumulada, en cambio, es honesta desde
el primer partido: no promete tendencia, solo enseña cómo se ha llegado hasta
aquí, y ahí sí se ve si un sobrerrendimiento viene de un partido suelto o de
todos.

**La forma reciente se compara consigo mismo, no con la liga.** Decir que un
jugador está en el percentil 80 de las últimas cinco jornadas mezcla dos cosas:
lo bueno que es y lo bien que está. Comparar sus últimos partidos con su propia
media de la temporada aísla la segunda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

# Partidos que se consideran "forma reciente". Cinco es la ventana con la que se
# habla de esto en fútbol, y es la más corta que no depende de un solo partido.
RECENT_MATCHES = 5

# Por debajo de esto no se habla de forma: con tres partidos, cualquier
# diferencia con la media de la temporada entra dentro de lo esperable.
MIN_MATCHES_FOR_FORM = 4


@dataclass(frozen=True, slots=True)
class MatchPoint:
    """Un partido dentro de la trayectoria."""

    match_label: str | None
    position: str | None
    minutes: int
    goals: int
    xg: float
    assists: int
    xa: float
    # Acumulados hasta ese partido incluido, que es lo que dibuja la curva.
    cumulative_goals: int
    cumulative_xg: float


@dataclass(frozen=True, slots=True)
class FormSummary:
    """Cómo está un jugador ahora frente a cómo ha ido la temporada."""

    matches: int
    recent_matches: int
    # xG por 90 en la ventana reciente y en toda la temporada.
    recent_xg90: float | None
    season_xg90: float | None
    recent_minutes: int
    caveat: str = ""

    @property
    def delta(self) -> float | None:
        """Cuánto se separa la ventana reciente de la media de la temporada."""
        if self.recent_xg90 is None or self.season_xg90 is None:
            return None
        return round(self.recent_xg90 - self.season_xg90, 3)


def trajectory(matches: pd.DataFrame) -> list[MatchPoint]:
    """Los partidos en orden, con los acumulados hasta cada uno.

    El orden lo da la etiqueta del partido, que empieza por la fecha: es lo que
    publica la fuente y evita depender de una columna de fecha que puede faltar.
    """
    if matches.empty:
        return []

    ordenados = matches.sort_values("match_label")
    goles = pd.to_numeric(ordenados["goals"], errors="coerce").fillna(0)
    xg = pd.to_numeric(ordenados["xg"], errors="coerce").fillna(0.0)

    acumulado_goles = goles.cumsum()
    acumulado_xg = xg.cumsum()

    puntos = []
    for posicion, (_, fila) in enumerate(ordenados.iterrows()):
        puntos.append(
            MatchPoint(
                match_label=_texto(fila.get("match_label")),
                position=_texto(fila.get("position")),
                minutes=_entero(fila.get("minutes")),
                goals=_entero(fila.get("goals")),
                xg=round(float(xg.iloc[posicion]), 3),
                assists=_entero(fila.get("assists")),
                xa=round(float(pd.to_numeric(fila.get("xa"), errors="coerce") or 0.0), 3),
                cumulative_goals=int(acumulado_goles.iloc[posicion]),
                cumulative_xg=round(float(acumulado_xg.iloc[posicion]), 3),
            )
        )
    return puntos


def form(matches: pd.DataFrame, window: int = RECENT_MATCHES) -> FormSummary:
    """Compara los últimos partidos con la media de la temporada del jugador.

    Se usa xG por 90 y no goles porque los goles de cinco partidos son casi
    todo azar: un delantero puede marcar dos en una racha sin haber generado
    nada, y al revés. El xG dice si está generando, que es lo que se sostiene.
    """
    if matches.empty:
        return FormSummary(0, 0, None, None, 0, "Sin partidos cargados.")

    ordenados = matches.sort_values("match_label")
    total = len(ordenados)
    recientes = ordenados.tail(window)

    aviso = ""
    if total < MIN_MATCHES_FOR_FORM:
        aviso = (
            f"Solo {total} partidos jugados: cualquier diferencia con la media de la "
            "temporada entra dentro de lo esperable por azar."
        )

    return FormSummary(
        matches=total,
        recent_matches=len(recientes),
        recent_xg90=_por_90(recientes),
        season_xg90=_por_90(ordenados),
        recent_minutes=int(pd.to_numeric(recientes["minutes"], errors="coerce").fillna(0).sum()),
        caveat=aviso,
    )


def _por_90(matches: pd.DataFrame) -> float | None:
    """xG por 90 minutos de un conjunto de partidos.

    Sin minutos no hay denominador: un jugador que ha entrado tres veces en el
    minuto 88 no tiene un xG por 90, tiene ruido dividido por un número pequeño.
    """
    minutos = pd.to_numeric(matches["minutes"], errors="coerce").fillna(0).sum()
    if minutos <= 0:
        return None
    xg = pd.to_numeric(matches["xg"], errors="coerce").fillna(0.0).sum()
    return round(float(xg) / float(minutos) * 90.0, 3)


def _entero(valor: object) -> int:
    numero = pd.to_numeric(valor, errors="coerce")
    return 0 if pd.isna(numero) else int(numero)


def _texto(valor: object) -> str | None:
    return None if valor is None or pd.isna(valor) else str(valor)
