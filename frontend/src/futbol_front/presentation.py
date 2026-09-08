"""Preparacion de datos para los graficos.

Separado de `charts` a proposito: aqui no se importa matplotlib ni mplsoccer,
solo se transforma la respuesta de la API en lo que el grafico necesita. Asi la
parte con reglas (que ejes, en que orden, que hacer con los huecos) se puede
testear, y el dibujo queda como una capa fina encima.
"""

from __future__ import annotations

import logging
import re
import unicodedata
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

    return PizzaData(labels=etiquetas, values=valores, categories=categorias, missing=ausentes)


@dataclass(frozen=True, slots=True)
class ComparisonData:
    """Dos jugadores sobre los mismos ejes."""

    labels: list[str]
    values_a: list[int]
    values_b: list[int]
    categories: list[str]
    missing: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.labels)


def prepare_comparison(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    template: list[dict[str, Any]],
) -> ComparisonData:
    """Prepara la comparacion de dos jugadores sobre la misma plantilla.

    Solo se conservan las metricas que **los dos** tienen: una porcion presente
    para uno y vacia para el otro se leeria como que el segundo vale cero en
    ella, que es una afirmacion falsa y ademas la mas danina posible en un
    grafico pensado para compararlos de un vistazo.

    Comparar solo tiene sentido si ambos percentiles salen de la misma
    poblacion. Quien llama debe pedir los dos perfiles con la misma temporada y
    la misma base de comparacion.
    """
    uno = prepare_pizza(profile_a, template)
    dos = prepare_pizza(profile_b, template)

    comunes = set(uno.labels) & set(dos.labels)
    indices_a = {etiqueta: i for i, etiqueta in enumerate(uno.labels)}
    indices_b = {etiqueta: i for i, etiqueta in enumerate(dos.labels)}

    etiquetas, valores_a, valores_b, categorias = [], [], [], []
    for i, etiqueta in enumerate(uno.labels):
        if etiqueta not in comunes:
            continue
        etiquetas.append(etiqueta)
        valores_a.append(uno.values[indices_a[etiqueta]])
        valores_b.append(dos.values[indices_b[etiqueta]])
        categorias.append(uno.categories[i])

    ausentes = sorted(set(uno.missing) | set(dos.missing))
    return ComparisonData(
        labels=etiquetas,
        values_a=valores_a,
        values_b=valores_b,
        categories=categorias,
        missing=ausentes,
    )


def _percentil(valor: float, metrica: str) -> int:
    """Redondea a entero y recorta al rango valido."""
    entero = int(round(valor))
    if entero < MIN_PERCENTILE or entero > MAX_PERCENTILE:
        logger.warning("Percentil fuera de rango", extra={"metrica": metrica, "valor": valor})
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


def chart_filename(*partes: str, extension: str = "png") -> str:
    """Nombre de fichero para un grafico descargado.

    Los nombres de jugador y equipo llevan acentos, espacios y algun punto
    ("A. Garcia"), que dan problemas al guardar segun el sistema. Se pasan a
    ASCII y se unen con guiones, que es lo que sobrevive a cualquier sitio donde
    acabe el fichero: el escritorio, un adjunto o un gestor de contenidos.

    >>> chart_filename("Nico Williams", "2627", "per90")
    'nico-williams-2627-per90.png'
    """
    limpias = [_slug(parte) for parte in partes if _slug(parte)]
    nombre = "-".join(limpias) or "grafico"
    return f"{nombre}.{extension}"


def _slug(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")
