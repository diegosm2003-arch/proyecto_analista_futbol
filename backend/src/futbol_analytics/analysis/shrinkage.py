"""Corrección por tamaño de muestra.

La plataforma ya avisa de que un percentil con pocos minutos es frágil. Esto es
el paso siguiente: corregirlo.

**El problema.** Un jugador con 135 minutos en el percentil 91 y otro con 2.500
en el percentil 91 no son comparables. El primero es en buena parte ruido, y la
interfaz los enseña igual delegando la interpretación en quien mira.

**La corrección.** En lugar del valor observado se usa uno contraído hacia la
media de su población, con un peso que crece con los minutos:

    ajustado = w * observado + (1 - w) * media,   con  w = minutos / (minutos + k)

Con muchos minutos `w` tiende a 1 y el valor apenas se toca; con pocos, tira
hacia la media, que es exactamente lo que dice la evidencia: de un jugador del
que sabemos poco, lo más razonable que se puede afirmar es que se parece al
resto.

**`k` no es igual para todas las métricas, y ahí está el fútbol.** `k` son los
minutos a los que la métrica ya pesa la mitad, y depende de cómo de frecuente es
el evento que mide. Los tiros ocurren varias veces por partido y estabilizan
rápido; los goles menos xG dependen de eventos raros y no estabilizan ni en una
temporada entera. Aplicar la misma constante a las dos trataría igual algo que
se sabe en cuatro partidos y algo que no se sabe en cuarenta.

**Qué NO hace esto.** No convierte una muestra pequeña en un dato bueno: la
contracción reconoce la ignorancia, no la elimina. Un delantero con 200 minutos
seguirá sin ser comparable con uno de 2.500; lo que cambia es que su percentil
deja de afirmar que lo es.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Minutos a los que cada metrica pesa la mitad. Son ordenes de magnitud
# elegidos por criterio futbolistico, no estimados de los datos: para estimarlos
# bien hace falta partir varias temporadas por la mitad y correlacionarlas, y
# con dos temporadas cargadas esa estimacion seria tan ruidosa como el problema
# que intenta resolver.
#
# El criterio es la frecuencia del evento que mide cada una:
#
# - Los tiros ocurren varias veces por partido: con cinco o seis partidos ya se
#   sabe si alguien dispara mucho.
# - El xG y el xA acumulan sobre eventos moderadamente frecuentes.
# - Las cadenas de posesion tocan a mucha gente en cada jugada, asi que se
#   estabilizan pronto.
# - Los goles son eventos raros. Y la diferencia entre goles y xG es lo mas
#   lento de todo: casi todo es varianza por debajo de una temporada completa.
HALF_LIFE_MINUTES: dict[str, int] = {
    "shots": 450,
    "key_passes": 500,
    "xg_chain": 500,
    "xg_buildup": 550,
    "xa": 700,
    "np_xg": 750,
    "assists": 1100,
    "goals": 1400,
    "np_goals": 1400,
}

# Para lo que no esta en la tabla. Deliberadamente alto: ante una metrica
# desconocida, es mejor contraer de mas que afirmar de mas.
DEFAULT_HALF_LIFE = 900


def weight(minutes: float, half_life: int) -> float:
    """Cuánto pesa lo observado frente a la media de la población.

    Va de 0 a 1 y vale exactamente 0,5 cuando los minutos igualan a `half_life`,
    que es lo que hace que la constante se pueda leer y discutir en minutos de
    juego en lugar de como un parámetro abstracto.
    """
    if minutes <= 0 or half_life <= 0:
        return 0.0
    return float(minutes) / (float(minutes) + float(half_life))


def shrink(
    players: pd.DataFrame,
    metric: str,
    value_column: str,
    group_columns: tuple[str, ...] = ("league", "season", "position_group"),
) -> pd.Series:
    """Contrae los valores de una métrica hacia la media de su grupo.

    El grupo es la población contra la que se compara, no toda la liga: la media
    a la que tiene sentido acercar a un central es la de los centrales, no la de
    todos los futbolistas.
    """
    if players.empty or value_column not in players.columns:
        return pd.Series(dtype="float64")

    valores = pd.to_numeric(players[value_column], errors="coerce")
    minutos = pd.to_numeric(players.get("minutes"), errors="coerce").fillna(0)

    presentes = [c for c in group_columns if c in players.columns]
    medias = (
        valores.groupby([players[c] for c in presentes]).transform("mean")
        if presentes
        else pd.Series(valores.mean(), index=valores.index)
    )

    k = HALF_LIFE_MINUTES.get(metric, DEFAULT_HALF_LIFE)
    peso = minutos / (minutos + k)
    # Sin media de grupo no hay hacia donde contraer: se deja el valor tal cual
    # en lugar de inventarse una referencia.
    return valores.where(medias.isna(), peso * valores + (1 - peso) * medias)


def reliability(minutes: float, metric: str) -> float:
    """Qué parte del valor de un jugador es suya y no de la media.

    Es el mismo peso de la contracción, expuesto aparte para que la interfaz
    pueda enseñarlo: un 0,3 significa que dos tercios de lo que se ve viene de
    parecerse al resto, y eso el usuario tiene derecho a saberlo.
    """
    return round(weight(minutes, HALF_LIFE_MINUTES.get(metric, DEFAULT_HALF_LIFE)), 3)


def slowest_metrics(threshold: int = 1000) -> tuple[str, ...]:
    """Métricas que no estabilizan por debajo de una temporada larga.

    Sirve para avisar con más fuerza donde hace falta: un percentil de goles con
    trescientos minutos merece una advertencia que uno de tiros no necesita.
    """
    return tuple(nombre for nombre, k in sorted(HALF_LIFE_MINUTES.items()) if k >= threshold)
