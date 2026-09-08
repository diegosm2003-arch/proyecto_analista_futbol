"""Normalizacion previa al analisis: por 90 minutos y por posesion.

La base de datos guarda totales. Aqui se convierten en lo que de verdad se
compara. Son funciones puras sobre DataFrames: ni base de datos ni red.
"""

from __future__ import annotations

import logging

import pandas as pd

from futbol_analytics.metrics import Metric

logger = logging.getLogger(__name__)

# Posesion de referencia a la que se normaliza el ajuste. 50 % es el equipo
# medio por definicion: un equipo que tiene el balon la mitad del tiempo.
NEUTRAL_POSSESSION = 50.0

# Limites para la posesion. Un valor fuera de rango solo puede venir de un dato
# corrupto, y sin recortar dispararia el factor de ajuste.
MIN_POSSESSION = 25.0
MAX_POSSESSION = 75.0


def per_90(frame: pd.DataFrame, metrics: tuple[Metric, ...]) -> pd.DataFrame:
    """Anade una columna `<metrica>_p90` por cada metrica normalizable.

    Es la comparacion justa por defecto: un jugador con 900 minutos y otro con
    2.700 no se pueden comparar en totales.
    """
    result = frame.copy()
    if "minutes" not in result.columns:
        raise KeyError("Hace falta la columna 'minutes' para normalizar por 90.")

    noventas = pd.to_numeric(result["minutes"], errors="coerce") / 90.0
    # Un jugador con cero minutos no tiene ratio: NaN, nunca division por cero.
    noventas = noventas.where(noventas > 0)

    for metric in metrics:
        if not metric.per90 or metric.name not in result.columns:
            continue
        result[f"{metric.name}_p90"] = (
            pd.to_numeric(result[metric.name], errors="coerce") / noventas
        )
    return result


def team_possession(teams: pd.DataFrame) -> pd.Series:
    """Posesion media por equipo y temporada, en porcentaje.

    Usa la posesion que publica FBref si esta disponible. Si no, la aproxima con
    la cuota de pases: un equipo que intenta el 60 % de los pases del partido
    tiene aproximadamente el 60 % del balon. No es identica a la posesion
    cronometrada, pero ordena a los equipos igual de bien, que es lo que necesita
    el ajuste.

    Devuelve una serie indexada por (league, season, team).
    """
    claves = ["league", "season", "team"]
    faltan = [clave for clave in claves if clave not in teams.columns]
    if faltan:
        raise KeyError(f"Faltan columnas de clave de equipo: {faltan}")

    a_favor = teams[teams["perspective"] == "for"].set_index(claves)
    en_contra = teams[teams["perspective"] == "against"].set_index(claves)

    if "possession_pct" in a_favor.columns:
        directa = pd.to_numeric(a_favor["possession_pct"], errors="coerce")
        if directa.notna().any():
            return directa.clip(MIN_POSSESSION, MAX_POSSESSION).rename("possession_pct")

    if "passes_attempted" not in a_favor.columns or "passes_attempted" not in en_contra.columns:
        raise KeyError(
            "Sin 'possession_pct' ni 'passes_attempted' no se puede estimar la posesion."
        )

    logger.info("FBref no ha dado posesion; se aproxima con la cuota de pases")
    propios = pd.to_numeric(a_favor["passes_attempted"], errors="coerce")
    rivales = pd.to_numeric(en_contra["passes_attempted"], errors="coerce")

    total = propios.add(rivales)
    cuota = (propios / total.where(total > 0)) * 100.0
    return cuota.clip(MIN_POSSESSION, MAX_POSSESSION).rename("possession_pct")


def possession_adjust(
    players: pd.DataFrame,
    metrics: tuple[Metric, ...],
    possession: pd.Series,
) -> pd.DataFrame:
    """Anade `<metrica>_padj` a las metricas sensibles a la posesion.

    El problema que resuelve: un pivote de un equipo que tiene el 65 % del balon
    dispone de mucho menos tiempo para robar que uno de un equipo que tiene el
    35 %. Sin ajustar, el segundo parece mejor recuperador aunque sean iguales.

    El ajuste escala las acciones defensivas al equipo que tendria el 50 % de
    posesion:

        padj = p90 * 50 / (100 - posesion_del_equipo)

    donde `100 - posesion` es el tiempo que el equipo pasa sin balon. Un equipo
    con el 70 % de posesion multiplica por 50/30 = 1,67.

    Es un ajuste util, no una verdad: asume que las ocasiones de defender son
    proporcionales al tiempo sin balon, lo que ignora donde se defiende. Por eso
    la interfaz ofrece las dos versiones y no sustituye una por la otra.
    """
    result = players.copy()
    claves = ["league", "season", "team"]

    posesion = result.set_index(claves).index.map(possession)
    posesion = pd.Series(posesion, index=result.index, dtype="float64")

    sin_posesion = (100.0 - posesion).where(lambda serie: serie > 0)
    factor = NEUTRAL_POSSESSION / sin_posesion

    desconocidos = int(posesion.isna().sum())
    if desconocidos:
        logger.warning(
            "Jugadores sin posesion de equipo conocida: se quedan sin ajuste",
            extra={"jugadores": desconocidos},
        )

    for metric in metrics:
        if not metric.possession_sensitive:
            continue
        columna_p90 = f"{metric.name}_p90"
        if columna_p90 not in result.columns:
            continue
        result[f"{metric.name}_padj"] = result[columna_p90] * factor

    return result


def eligible(players: pd.DataFrame, min_minutes: int) -> pd.DataFrame:
    """Poblacion valida para comparar: minutos suficientes y posicion conocida.

    El filtro se aplica ANTES de calcular percentiles, no despues. Es la
    diferencia entre un percentil util y uno inflado: si en la poblacion entran
    jugadores con 40 minutos, un delantero que marco en su unica aparicion
    aparece en el percentil 99 de goles por 90, y arrastra la distribucion de
    todos los demas.

    Sin `position_group` no hay poblacion de referencia, asi que esos jugadores
    tambien quedan fuera.
    """
    minutos = pd.to_numeric(players["minutes"], errors="coerce")
    valido = (minutos >= min_minutes) & players["position_group"].notna()

    descartados = int((~valido).sum())
    if descartados:
        logger.info(
            "Jugadores fuera de la poblacion de comparacion",
            extra={"jugadores": descartados, "min_minutes": min_minutes},
        )
    return players[valido].copy()
