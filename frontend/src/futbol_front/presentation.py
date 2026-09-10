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
        logger.info("Métricas sin percentil en el perfil", extra={"métricas": ausentes})

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
        logger.warning("Percentil fuera de rango", extra={"métrica": metrica, "valor": valor})
    return max(MIN_PERCENTILE, min(MAX_PERCENTILE, entero))


@dataclass(frozen=True, slots=True)
class StyleMapData:
    """Puntos del mapa de estilos de equipo."""

    teams: list[str]
    territory: list[float]
    ppda: list[float]
    styles: list[str]
    clusters: list[int]

    def __len__(self) -> int:
        return len(self.teams)


def prepare_style_map(report: dict[str, Any]) -> StyleMapData:
    """Ordena los equipos para el mapa de estilos.

    Los ejes son **territorio y presion**, no posesion y presion. Understat no
    publica posesion, asi que ese eje no existe; los dos que se usan salen de
    datos reales: llegadas a zona de remate por partido, que dice cuanto campo
    pisa un equipo de verdad, y PPDA, que dice como de arriba defiende.

    Es ademas un plano mejor que el clasico de posesion: tener el balon y pisar
    el campo rival no son lo mismo, y hay equipos que acumulan pases lejos del
    area.
    """
    equipos, territorio, ppda, clusters, estilos = [], [], [], [], []
    for fila in report.get("teams", []):
        x, y = fila.get("territory"), fila.get("ppda")
        if x is None or y is None:
            continue
        equipos.append(fila["team"])
        territorio.append(float(x))
        ppda.append(float(y))
        clusters.append(int(fila["cluster"]))
        estilos.append(fila["style"])

    return StyleMapData(
        teams=equipos,
        territory=territorio,
        ppda=ppda,
        clusters=clusters,
        styles=estilos,
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
        return "Sin métricas suficientes para resumir el perfil."

    mejores = sorted(con_direccion, key=lambda m: m["percentile"], reverse=True)[:2]
    partes = [f"{m['label'].lower()} (percentil {int(round(m['percentile']))})" for m in mejores]
    return "Destaca en " + " y en ".join(partes) + "."


# Percentiles a partir de los cuales una metrica merece que se la senale. El 90
# y el 10 no son arbitrarios: es el uno de cada diez por arriba y por abajo, el
# corte con el que se habla de un jugador en un informe de scouting.
HIGH_PERCENTILE = 90
LOW_PERCENTILE = 10

# Cuantos avisos se ensenan como mucho.
MAX_ALERTS = 6

# Por debajo de esta poblacion el percentil se mueve demasiado con cada jugador
# que entra o sale como para construir un aviso sobre el.
FRAGILE_POPULATION = 50


@dataclass(frozen=True, slots=True)
class Alert:
    """Una metrica lo bastante extrema como para senalarla."""

    metric: str
    label: str
    percentile: int
    # "fortaleza", "debilidad" o "rasgo".
    kind: str
    # Como hay que leer el dato. Vacio cuando no hay nada que matizar.
    note: str = ""

    @property
    def text(self) -> str:
        return f"{self.label}: percentil {self.percentile}"


def extreme_metrics(
    profile: dict[str, Any],
    high: int = HIGH_PERCENTILE,
    low: int = LOW_PERCENTILE,
) -> list[Alert]:
    """Métricas en las que el jugador se sale de lo normal, con su lectura.

    Un pizza chart con doce ejes ensena mucho a la vez y no dice donde mirar.
    Esto responde a la pregunta que se hace un analista delante del grafico: que
    tiene este jugador de verdaderamente distinto.

    **Un extremo no siempre es bueno ni malo.** Se separan tres casos:

    - Metricas con direccion (`higher_is_better`): el percentil ya viene
      invertido donde menos es mejor, asi que arriba es fortaleza y abajo,
      debilidad.
    - Metricas de estilo, sin direccion: un percentil 97 en tiros no es un
      elogio, es un perfil de jugador que dispara mucho. Se marca como rasgo, y
      si acierta o no lo dicen las metricas de finalizacion, no esta.

    **Dos matices que evitan leer de mas.** Las metricas que el catalogo marca
    como dependientes del equipo miden al conjunto tanto como al jugador: en
    xGBuildup los centrales del Barcelona salen entre los mejores de la liga, y
    no es que construyan mejor que nadie, es que su equipo tiene el balon. Y con
    una poblacion pequena el percentil entero es fragil, asi que se avisa en
    todos los avisos en lugar de fingir precision.
    """
    poblacion_fragil = profile.get("population_size", 0) < FRAGILE_POPULATION

    avisos = []
    for metrica in profile.get("metrics", []):
        percentil = metrica.get("percentile")
        if percentil is None:
            continue
        percentil = int(round(percentil))
        if not (percentil >= high or percentil <= low):
            continue

        # Sin direccion la metrica es de estilo: describe al jugador, no lo
        # califica.
        direccion = metrica.get("higher_is_better")
        arriba = "fortaleza" if percentil >= high else "debilidad"
        tipo = "rasgo" if direccion is None else arriba

        avisos.append(
            Alert(
                metric=metrica.get("metric", ""),
                label=metrica.get("label", metrica.get("metric", "")),
                percentile=percentil,
                kind=tipo,
                note=_nota(metrica, poblacion_fragil),
            )
        )

    # Lo mas extremo primero: es el orden en que se miraria en un informe. Y se
    # corta ahi porque las metricas de ataque estan muy correlacionadas entre
    # si: un delantero en forma se sale en npxG, en goles y en tiros a la vez, y
    # listar las nueve diria tres veces lo mismo y taparia lo demas.
    ordenados = sorted(avisos, key=lambda a: abs(a.percentile - 50), reverse=True)
    return ordenados[:MAX_ALERTS]


def _nota(metrica: dict[str, Any], poblacion_fragil: bool) -> str:
    """Como hay que leer un percentil extremo de esta metrica."""
    notas = []
    if metrica.get("team_dependent"):
        notas.append(
            "cuenta posesiones, así que premia jugar en un equipo dominante: "
            "mide al conjunto tanto como al jugador"
        )
    if poblacion_fragil:
        notas.append("la población de comparación es pequeña y el percentil se mueve fácil")
    return "; ".join(notas)


def season_label(season: str) -> str:
    """Temporada en el formato con el que se habla de ella.

    `soccerdata` la codifica con cuatro digitos ("2627") porque es lo que espera
    la fuente, pero nadie dice "la dos seis dos siete": se dice 26/27. La barra
    ademas evita el otro problema del codigo crudo, que a primera vista parece un
    ano suelto o un identificador interno.

    >>> season_label("2627")
    '26/27'
    >>> season_label("raro")
    'raro'
    """
    if len(season) == 4 and season.isdigit():
        return f"{season[:2]}/{season[2:]}"
    return season


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
    # Sin tilde a proposito: este valor NO pasa por `_slug`, asi que una tilde
    # aqui produciria justo el nombre de fichero que esta funcion evita.
    nombre = "-".join(limpias) or "grafico"
    return f"{nombre}.{extension}"


def _slug(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")
