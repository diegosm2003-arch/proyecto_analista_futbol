"""Percentiles por posicion.

La regla que sostiene todo el producto: **el percentil se calcula contra la
poblacion completa de las Big 5 y solo despues se filtra la vista a LaLiga**.
Al reves, un lateral de LaLiga se compararia contra 80 laterales en lugar de
contra 400, y el percentil diria mas del ruido muestral que del jugador.

La poblacion se agrupa por temporada y grupo de posicion. Por temporada porque
el xG medio y el volumen de presion cambian de un ano a otro, y un percentil que
cruza temporadas compara a un jugador con un futbol que ya no se juega.
"""

from __future__ import annotations

import logging

import pandas as pd

from futbol_analytics.analysis import features
from futbol_analytics.metrics import Metric

logger = logging.getLogger(__name__)

# Columnas que identifican a un jugador en el resultado.
KEY_COLUMNS = ("league", "season", "team", "player")

# Agrupacion de la poblacion de referencia.
POPULATION_KEYS = ("season", "position_group")

# Contexto que viaja con cada fila del resultado. `detailed_position` solo esta
# presente si el clustering de roles ya se ha ejecutado sobre la poblacion.
CONTEXT_COLUMNS = ("position_group", "detailed_position", "minutes")

# Normalizaciones que se calculan. La interfaz deja elegir entre ellas: ver el
# mismo jugador en las dos versiones es, en si mismo, un hallazgo.
BASIS_PER90 = "per90"
BASIS_PADJ = "padj"


def compute(
    players: pd.DataFrame,
    metrics: tuple[Metric, ...],
    *,
    min_minutes: int,
    possession: pd.Series | None = None,
    population_keys: tuple[str, ...] = POPULATION_KEYS,
) -> pd.DataFrame:
    """Calcula los percentiles de cada jugador dentro de su poblacion.

    Args:
        players: Filas de `player_season`, con totales.
        metrics: Catalogo a evaluar.
        min_minutes: Umbral para entrar en la poblacion de comparacion.
        possession: Posesion por (league, season, team), de
            `features.team_possession`. Sin ella no se calcula la version
            ajustada por posesion.
        population_keys: Como se agrupa la poblacion de referencia.

    Returns:
        Formato largo, una fila por jugador y metrica, con columnas
        `value` (total), `per90`, `padj`, `percentile_per90`, `percentile_padj`
        y `higher_is_better`. Largo y no ancho porque es lo que consume un pizza
        chart y porque cada metrica lleva su propia interpretacion.
    """
    poblacion = features.eligible(players, min_minutes)
    if poblacion.empty:
        logger.warning("Ningun jugador supera el umbral de minutos")
        return _empty_result()

    poblacion = features.per_90(poblacion, metrics)
    if possession is not None:
        poblacion = features.possession_adjust(poblacion, metrics, possession)

    largo = _to_long(poblacion, metrics)
    if largo.empty:
        return _empty_result()

    interpretacion = {metric.name: metric.higher_is_better for metric in metrics}
    for base in (BASIS_PER90, BASIS_PADJ):
        largo[f"percentile_{base}"] = _rank_within_population(
            largo, base, interpretacion, population_keys
        )

    logger.info(
        "Percentiles calculados",
        extra={
            "jugadores": poblacion[list(KEY_COLUMNS)].drop_duplicates().shape[0],
            "metricas": largo["metric"].nunique(),
            "poblaciones": largo.groupby(list(population_keys)).ngroups,
        },
    )
    return largo


def for_player(
    percentiles: pd.DataFrame,
    player: str,
    season: str,
    *,
    basis: str = BASIS_PER90,
) -> pd.DataFrame:
    """Extrae el perfil de un jugador, listo para dibujar un pizza chart.

    Filtrar aqui y no antes de `compute` es lo que garantiza que el percentil se
    haya calculado contra toda la poblacion.
    """
    columna = f"percentile_{basis}"
    if columna not in percentiles.columns:
        raise ValueError(f"Base de comparacion desconocida: {basis!r}")

    perfil = percentiles[
        (percentiles["player"] == player) & (percentiles["season"] == season)
    ].copy()
    return perfil.dropna(subset=[columna]).sort_values(columna, ascending=False)


def _to_long(poblacion: pd.DataFrame, metrics: tuple[Metric, ...]) -> pd.DataFrame:
    """Pasa de una fila por jugador a una fila por jugador y metrica."""
    contexto = [columna for columna in CONTEXT_COLUMNS if columna in poblacion.columns]
    piezas = []
    for metric in metrics:
        if metric.name not in poblacion.columns or not metric.per90:
            continue

        pieza = poblacion[list(KEY_COLUMNS) + contexto].copy()
        pieza["metric"] = metric.name
        pieza["label"] = metric.label
        pieza["value"] = pd.to_numeric(poblacion[metric.name], errors="coerce")
        pieza[BASIS_PER90] = poblacion[f"{metric.name}_p90"]
        # Solo las metricas sensibles a la posesion tienen version ajustada;
        # para el resto la columna queda vacia y la interfaz no ofrece el
        # conmutador. Se fuerza a float para que el ranking no vea un object.
        ajustada = f"{metric.name}_padj"
        pieza[BASIS_PADJ] = poblacion[ajustada] if ajustada in poblacion.columns else float("nan")
        pieza["higher_is_better"] = metric.higher_is_better
        piezas.append(pieza)

    if not piezas:
        return _empty_result()
    return pd.concat(piezas, ignore_index=True)


def _rank_within_population(
    largo: pd.DataFrame,
    basis: str,
    interpretacion: dict[str, bool | None],
    population_keys: tuple[str, ...],
) -> pd.Series:
    """Percentil de cada valor dentro de su poblacion, de 0 a 100.

    Las metricas donde un valor bajo es mejor (faltas cometidas) se invierten,
    de modo que un percentil alto significa siempre "mejor" cuando la metrica
    tiene direccion. Las metricas de estilo (`higher_is_better=None`) no se
    invierten: su percentil describe donde esta el jugador, no si es bueno.
    """
    if basis not in largo.columns:
        return pd.Series(pd.NA, index=largo.index, dtype="float64")

    grupos = [*population_keys, "metric"]
    percentil = largo.groupby(grupos, dropna=False)[basis].rank(pct=True) * 100.0

    menor_es_mejor = largo["metric"].map(interpretacion).eq(False)
    return percentil.mask(menor_es_mejor, 100.0 - percentil)


def _empty_result() -> pd.DataFrame:
    columnas = [
        *KEY_COLUMNS,
        *CONTEXT_COLUMNS,
        "metric",
        "label",
        "value",
        BASIS_PER90,
        BASIS_PADJ,
        "higher_is_better",
        f"percentile_{BASIS_PER90}",
        f"percentile_{BASIS_PADJ}",
    ]
    return pd.DataFrame(columns=columnas)
