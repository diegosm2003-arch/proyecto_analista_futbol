"""Jugadores con un perfil parecido.

Responde a la pregunta con la que trabaja un scout: *este futbolista me gusta,
quien mas juega asi*. No es un ranking de calidad ni una recomendacion de
fichaje; es un vecindario dentro de un espacio de percentiles.

**Se comparan percentiles, no valores por 90.** Dos numeros crudos no son
comparables entre ligas ni entre posiciones, y ademas cada metrica tiene su
escala: los tiros por 90 se mueven entre 0 y 5, el xG entre 0 y 1. Con valores
crudos, la distancia la mandaria la metrica de numeros mas grandes. El percentil
lleva todo a la misma escala de 0 a 100 y ya incorpora la poblacion de
referencia.

**Solo se compara dentro del mismo grupo posicional.** Un central y un extremo
pueden tener percentiles parecidos y no parecerse en nada: el percentil de cada
uno esta calculado contra los suyos, asi que un 90 en tiros significa cosas
distintas. Comparar entre grupos produciria parecidos que no existen.

**La distancia es euclidea sobre el vector de percentiles**, normalizada a un
parecido de 0 a 100 para que se pueda leer. Se usa euclidea y no coseno a
proposito: el coseno mira la *forma* del perfil e ignora el nivel, con lo que un
delantero del percentil 95 en todo saldria identico a uno del percentil 30 en
todo. Para un scout eso es justo lo contrario de lo que quiere.

**No todas las metricas sirven para medir parecido.** Solo entran las de
aportacion; quedan fuera los denominadores (minutos, partidos) y las tarjetas.
El motivo es que una metrica donde casi todo el mundo vale lo mismo no separa a
nadie: practicamente ningun futbolista ve una roja en una temporada, asi que ese
eje daba a toda la poblacion por identica, inflaba el parecido de todos y
ademas salia como explicacion —"se parecen en tarjetas rojas"—, tapando lo que
de verdad los acercaba.

**Limitacion que hay que decir en voz alta:** el parecido solo abarca lo que
mide el catalogo. Hoy son metricas de ataque, asi que dos centrales "similares"
lo son en su aportacion con balon, no en como defienden.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Vecinos que se devuelven por defecto. Suficiente para ver un patron y no
# tantos como para que la lista deje de significar nada.
DEFAULT_NEIGHBOURS = 6

# Metricas comunes minimas para que una comparacion signifique algo. Con dos o
# tres ejes, cualquiera se parece a cualquiera.
MIN_SHARED_METRICS = 4

# Peor distancia posible entre dos vectores de percentiles: todos los ejes en
# extremos opuestos.
_MAX_PERCENTILE_GAP = 100.0


@dataclass(frozen=True, slots=True)
class Neighbour:
    """Un jugador parecido, con en que se parece y en que no."""

    league: str
    team: str
    player: str
    minutes: int | None
    similarity: float
    # Metricas donde mas se acercan y donde mas se separan, que es lo que
    # convierte una lista de nombres en algo que se puede defender.
    closest: tuple[str, ...]
    furthest: tuple[str, ...]
    # Percentil medio por familia (finalizacion, creacion, construccion). Es lo
    # que permite situar a cada uno en un plano y ver el vecindario, en lugar de
    # leer una lista de nombres y un porcentaje.
    profile: dict[str, float]


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """El jugador de referencia y su vecindario."""

    profile: dict[str, float]
    neighbours: list[Neighbour]


def _wide(percentiles: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Pasa el frame largo de percentiles a una fila por jugador."""
    columna = f"percentile_{basis}"
    if columna not in percentiles.columns:
        return pd.DataFrame()

    return percentiles.pivot_table(
        index=["league", "season", "team", "player"],
        columns="metric",
        values=columna,
        aggfunc="first",
    )


def nearest(
    percentiles: pd.DataFrame,
    player: str,
    team: str | None = None,
    basis: str = "per90",
    n: int = DEFAULT_NEIGHBOURS,
    min_minutes: int = 0,
    metrics: Sequence[str] | None = None,
    families: Mapping[str, Sequence[str]] | None = None,
) -> SimilarityResult:
    """Jugadores con el perfil de percentiles mas parecido al de uno dado.

    Se limita a su mismo grupo posicional y descarta a quien no llegue al umbral
    de minutos: un perfil construido sobre 90 minutos no se parece a nada, solo
    es ruido con forma de jugador.

    `metrics` acota los ejes de comparacion. Quien llama pasa las de aportacion:
    los denominadores y las tarjetas no separan a nadie y ensucian el resultado.

    `families` agrupa metricas para devolver un percentil medio por familia
    (finalizacion, creacion, construccion). Sirve para situar a cada jugador en
    un plano: una lista de nombres con un porcentaje no ensena donde esta el
    vecindario, y un plano si.
    """
    vacio = SimilarityResult(profile={}, neighbours=[])
    if percentiles.empty or "position_group" not in percentiles.columns:
        return vacio

    ancho = _wide(percentiles, basis)
    if ancho.empty:
        return vacio

    contexto = (
        percentiles[["league", "season", "team", "player", "position_group", "minutes"]]
        .drop_duplicates(subset=["league", "season", "team", "player"])
        .set_index(["league", "season", "team", "player"])
    )
    tabla = ancho.join(contexto, how="inner")

    objetivo = tabla[tabla.index.get_level_values("player") == player]
    if team is not None:
        objetivo = objetivo[objetivo.index.get_level_values("team") == team]
    if objetivo.empty:
        return vacio
    if len(objetivo) > 1:
        # Un jugador con dos etapas en la temporada. Sin saber cual se pide, no
        # se elige por el aqui: quien llama tiene que concretar el equipo.
        logger.info("Jugador con varias etapas", extra={"jugador": player})
        return vacio

    grupo = objetivo.iloc[0]["position_group"]
    if pd.isna(grupo):
        return vacio

    metricas = [c for c in ancho.columns if c in tabla.columns]
    if metrics is not None:
        permitidas = set(metrics)
        metricas = [c for c in metricas if c in permitidas]
    vector = objetivo.iloc[0][metricas].astype("float64")
    ejes = [m for m in metricas if pd.notna(vector[m])]
    if len(ejes) < MIN_SHARED_METRICS:
        logger.info(
            "Perfil con muy pocos ejes para comparar",
            extra={"jugador": player, "ejes": len(ejes)},
        )
        return vacio

    candidatos = tabla[(tabla["position_group"] == grupo) & (tabla.index != objetivo.index[0])]
    minutos = pd.to_numeric(candidatos["minutes"], errors="coerce")
    candidatos = candidatos[minutos.fillna(0) >= min_minutes]
    referencia = _perfil(objetivo.iloc[0], families)
    if candidatos.empty:
        return SimilarityResult(profile=referencia, neighbours=[])

    valores = candidatos[ejes].astype("float64")
    # Un hueco no puede contar como parecido ni como diferencia enorme. Se
    # sustituye por el propio valor del jugador de referencia, que deja ese eje
    # sin efecto en la distancia en lugar de inventarse una separacion.
    diferencias = valores.sub(vector[ejes]).fillna(0.0)

    distancia = np.sqrt((diferencias**2).sum(axis=1))
    # Se normaliza por el peor caso posible con ese numero de ejes, para que el
    # parecido se pueda leer como un porcentaje y no dependa de cuantas metricas
    # tenga la posicion.
    peor = _MAX_PERCENTILE_GAP * np.sqrt(len(ejes))
    parecido = (1.0 - distancia / peor) * 100.0

    mejores = parecido.sort_values(ascending=False).head(max(0, n))
    absolutas = diferencias.abs()

    vecinos = []
    for clave, valor in mejores.items():
        liga, _temporada, equipo, nombre = clave
        fila = absolutas.loc[clave].sort_values()
        vecinos.append(
            Neighbour(
                league=liga,
                team=equipo,
                player=nombre,
                minutes=_entero(candidatos.loc[clave, "minutes"]),
                similarity=round(float(valor), 1),
                closest=tuple(fila.head(2).index),
                furthest=tuple(fila.tail(2).index[::-1]),
                profile=_perfil(candidatos.loc[clave], families),
            )
        )
    return SimilarityResult(profile=referencia, neighbours=vecinos)


def _perfil(fila: pd.Series, families: Mapping[str, Sequence[str]] | None) -> dict[str, float]:
    """Percentil medio de un jugador en cada familia de metricas.

    Se promedia y no se suma para que el numero siga siendo un percentil legible
    de 0 a 100, y no dependa de cuantas metricas tenga la familia.
    """
    if not families:
        return {}

    resultado = {}
    for familia, metricas in families.items():
        valores = [float(fila[m]) for m in metricas if m in fila.index and pd.notna(fila.get(m))]
        if valores:
            resultado[familia] = round(sum(valores) / len(valores), 1)
    return resultado


def _entero(valor: object) -> int | None:
    try:
        if pd.isna(valor):  # type: ignore[arg-type]
            return None
        return int(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
