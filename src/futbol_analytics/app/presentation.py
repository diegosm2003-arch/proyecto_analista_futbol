"""Preparacion de datos para los graficos.

Separado de `charts` a proposito: aqui no se importa matplotlib ni mplsoccer,
solo se transforma la respuesta de la API en lo que el grafico necesita. Asi la
parte con reglas (que ejes, en que orden, que hacer con los huecos) se puede
testear, y el dibujo queda como una capa fina encima.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Un percentil solo se puede pintar de 0 a 100. Los valores que llegan fuera de
# rango serian un error de calculo, no un dato: se recortan y se registra.
MIN_PERCENTILE, MAX_PERCENTILE = 0, 100


@dataclass(frozen=True, slots=True)
class PizzaData:
    """Lo que necesita el pizza chart, ya ordenado."""

    labels: list[str]
    values: list[int]
    categories: list[str]
    # Metricas de la plantilla que la API no ha devuelto o que llegan sin
    # percentil. Se listan para poder avisar: un grafico con menos ejes de los
    # esperados no debe pasar desapercibido.
    missing: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.values)


def prepare_pizza(profile: dict[str, Any], template: list[dict[str, Any]]) -> PizzaData:
    """Ordena los percentiles del perfil segun la plantilla de su posicion.

    El orden lo manda la plantilla, no la respuesta: las porciones tienen que
    caer siempre en el mismo sitio para que dos graficos sean comparables de un
    vistazo. Por eso no se usa el orden por percentil que devuelve la API.
    """
    por_metrica = {metrica["metric"]: metrica for metrica in profile.get("metrics", [])}

    etiquetas: list[str] = []
    valores: list[int] = []
    categorias: list[str] = []
    ausentes: list[str] = []

    for porcion in template:
        metrica = por_metrica.get(porcion["metric"])
        percentil = metrica.get("percentile") if metrica else None
        if percentil is None:
            ausentes.append(porcion["metric"])
            continue

        etiquetas.append(porcion["label"])
        valores.append(_percentil(percentil, porcion["metric"]))
        categorias.append(porcion["category"])

    if ausentes:
        logger.info("Metricas sin percentil en el perfil", extra={"metricas": ausentes})

    return PizzaData(
        labels=etiquetas, values=valores, categories=categorias, missing=ausentes
    )


def _percentil(valor: float, metrica: str) -> int:
    """Redondea a entero y recorta al rango valido."""
    entero = int(round(valor))
    if entero < MIN_PERCENTILE or entero > MAX_PERCENTILE:
        logger.warning(
            "Percentil fuera de rango", extra={"metrica": metrica, "valor": valor}
        )
    return max(MIN_PERCENTILE, min(MAX_PERCENTILE, entero))


@dataclass(frozen=True, slots=True)
class StyleMapData:
    """Puntos del mapa de estilos de equipo."""

    teams: list[str]
    possession: list[float]
    ppda: list[float]
    styles: list[str]
    clusters: list[int]

    def __len__(self) -> int:
        return len(self.teams)


def prepare_style_map(report: dict[str, Any]) -> StyleMapData:
    """Extrae los equipos con posesion y presion conocidas.

    Un equipo al que le falte alguno de los dos ejes se descarta en lugar de
    pintarse en el cero: colocarlo en una esquina del mapa afirmaria que no
    presiona nada, que es una lectura distinta de "no lo sabemos".
    """
    equipos, posesion, ppda, estilos, clusters = [], [], [], [], []

    for equipo in report.get("teams", []):
        if equipo.get("possession") is None or equipo.get("ppda") is None:
            logger.info("Equipo sin ejes completos", extra={"equipo": equipo.get("team")})
            continue
        equipos.append(equipo["team"])
        posesion.append(float(equipo["possession"]))
        ppda.append(float(equipo["ppda"]))
        estilos.append(equipo.get("style", "sin estilo"))
        clusters.append(int(equipo.get("cluster", 0)))

    return StyleMapData(
        teams=equipos, possession=posesion, ppda=ppda, styles=estilos, clusters=clusters
    )


def summarise_profile(profile: dict[str, Any]) -> str:
    """Frase corta que resume el perfil, para acompanar al grafico.

    Toma los dos percentiles mas altos entre las metricas que si tienen
    direccion. Las de estilo se excluyen: decir que un jugador esta en el
    percentil 95 de despejes no es un elogio, es una descripcion, y en una frase
    de resumen se leeria como lo primero.
    """
    con_direccion = [
        metrica
        for metrica in profile.get("metrics", [])
        if metrica.get("higher_is_better") is True and metrica.get("percentile") is not None
    ]
    if not con_direccion:
        return "Sin metricas suficientes para resumir el perfil."

    mejores = sorted(con_direccion, key=lambda m: m["percentile"], reverse=True)[:2]
    partes = [f"{m['label'].lower()} (percentil {int(round(m['percentile']))})" for m in mejores]
    return "Destaca en " + " y en ".join(partes) + "."
