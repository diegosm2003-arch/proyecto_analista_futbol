"""Catalogo de metricas.

Es la pieza central de la fase de datos: define QUE se guarda y por que tiene
sentido futbolistico. De este catalogo se generan las columnas de las tablas de
PostgreSQL, asi que esquema y catalogo no pueden divergir.

**La fuente es Understat.** El proyecto nacio sobre FBref, pero FBref sirve
vacias sus tablas avanzadas: comprobado en 2023/24, 2024/25 y 2025/26, las
paginas de pase, posesion, defensa y creacion traen la tabla completa de
jugadores con todas las celdas de estadisticas sin un solo numero. Understat, en
cambio, publica la familia xG entera y ademas da un identificador estable de
jugador.

El catalogo es mas corto que el que se diseno sobre FBref, pero no mas pobre:
xGChain y xGBuildup permiten separar al finalizador del creador y del
constructor, que es una lectura que las estadisticas de conteo no dan.

Dos reglas de diseno se mantienen:

1. **Se guardan totales, nunca valores por 90 minutos.** El per-90 depende del
   umbral de minutos y de la poblacion de comparacion: es una decision de
   analisis, no un hecho que persistir.
2. **Se guardan metricas con significado, no todo lo que la fuente publica.**

El campo `column` es el nombre que usa la fuente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Grupos de posicion tal y como los da FBref a nivel de temporada.
ALL_POSITIONS: tuple[str, ...] = ("GK", "DF", "MF", "FW")
OUTFIELD: tuple[str, ...] = ("DF", "MF", "FW")

Dtype = Literal["int", "float"]


@dataclass(frozen=True, slots=True)
class Metric:
    """Una metrica del catalogo.

    Attributes:
        name: Nombre canonico. Es el nombre de la columna en PostgreSQL.
        stat_type: Tabla de FBref de la que sale (`stat_type` de soccerdata).
        column: Nombre de la columna de FBref una vez aplanada.
        label: Etiqueta legible, para graficos y documentacion.
        dtype: Tipo en la base de datos.
        positions: Posiciones para las que la metrica es informativa. Guia la
            eleccion de ejes del pizza chart en la fase de analisis.
        higher_is_better: Si un valor alto es mejor. `None` cuando depende del
            estilo del equipo y no se puede leer como bueno o malo (p. ej. los
            despejes: muchos pueden significar buen trabajo defensivo o
            simplemente un equipo que defiende muy atras).
        per90: Si tiene sentido normalizar por 90 minutos. Falso para los
            propios minutos y para metricas que ya son un promedio.
        required: Si su ausencia en el scraping debe considerarse un error. Las
            opcionales son metricas que FBref ha ido anadiendo y que pueden no
            existir en temporadas antiguas.
        source: De donde sale. `fbref` para las tablas de FBref, `understat`
            para las de Understat. Hizo falta cuando quedo claro que FBref sirve
            vacias sus tablas avanzadas: la familia xG viene de Understat.
        possession_sensitive: Si el volumen de la metrica depende de cuanto
            tiempo pasa el equipo sin balon. Un pivote de un equipo que domina
            tiene menos ocasiones de entrar que uno de un equipo replegado, asi
            que su valor por 90 mide al equipo tanto como al jugador. Estas
            metricas se ofrecen tambien ajustadas por posesion.
        team_dependent: Si la metrica premia jugar en un equipo dominante. Es lo
            contrario del caso anterior y no se corrige con el mismo ajuste: no
            sube al defender menos, sube al tener mas el balon. No hay ajuste
            que la arregle, asi que se marca para poder avisar al leerla.
    """

    name: str
    stat_type: str
    column: str
    label: str
    dtype: Dtype = "float"
    positions: tuple[str, ...] = ALL_POSITIONS
    higher_is_better: bool | None = True
    per90: bool = True
    required: bool = True
    source: str = "fbref"
    possession_sensitive: bool = False
    team_dependent: bool = False


# ---------------------------------------------------------------------------
# Jugadores
# ---------------------------------------------------------------------------

# El catalogo se mantiene con la disposicion compacta de una tabla, que es como
# se lee y se revisa: un argumento por linea lo haria tres veces mas largo sin
# ganar claridad. Por eso se excluye del formateador automatico.
# fmt: off
PLAYER_METRICS: tuple[Metric, ...] = (
    # --- Volumen de juego. No son metricas de rendimiento: son el denominador.
    Metric("minutes", "player_season", "minutes", "Minutos",
           dtype="int", per90=False, higher_is_better=None, source="understat"),
    Metric("matches_played", "player_season", "matches", "Partidos jugados",
           dtype="int", per90=False, higher_is_better=None, source="understat"),

    # --- Finalizacion. Que hace el jugador cuando le toca rematar.
    Metric("goals", "player_season", "goals", "Goles",
           positions=OUTFIELD, source="understat"),
    # Sin penaltis: quien los tira dice mas del designado que del jugador.
    Metric("np_goals", "player_season", "np_goals", "Goles sin penaltis",
           positions=OUTFIELD, source="understat"),
    Metric("np_xg", "player_season", "np_xg", "xG sin penaltis",
           positions=OUTFIELD, source="understat"),
    Metric("shots", "player_season", "shots", "Tiros",
           positions=OUTFIELD, source="understat"),

    # --- Creacion. Lo que genera para otros.
    Metric("assists", "player_season", "assists", "Asistencias",
           positions=OUTFIELD, source="understat"),
    Metric("xa", "player_season", "xa", "xA (asistencias esperadas)",
           positions=OUTFIELD, source="understat"),
    Metric("key_passes", "player_season", "key_passes", "Pases clave",
           positions=OUTFIELD, source="understat"),

    # --- Construccion. La aportacion que no acaba en sus botas.
    #
    # xGChain reparte el xG de una jugada entre todos los que la tocaron: mide
    # estar en las posesiones que acaban en tiro, se remate o no.
    Metric("xg_chain", "player_season", "xg_chain", "xGChain",
           positions=OUTFIELD, source="understat", team_dependent=True),
    # xGBuildup es xGChain quitando el tiro y la asistencia. Aisla a quien
    # construye sin finalizar, que es el perfil que ninguna estadistica de
    # conteo refleja: el central que saca el balon o el pivote que hace de
    # bisagra no aparecen en goles ni en asistencias.
    # Marcadas como dependientes del equipo: cuentan posesiones, y un equipo que
    # tiene el balon genera mas para todos los suyos. En nuestros datos, tras De
    # Jong y Pedri, los siguientes en xGBuildup son la defensa del Barcelona
    # entera. No es que construyan mejor que nadie.
    Metric("xg_buildup", "player_season", "xg_buildup", "xGBuildup",
           positions=OUTFIELD, source="understat", team_dependent=True),

    # --- Disciplina. Sin direccion a proposito: describen como compite un
    # jugador, no lo bueno que es. Dar por mejor al que menos tarjetas ve
    # premiaria al pivote que no hace la falta tactica y al central que no sale
    # a cortar. Con direccion, el aviso de percentiles extremos llegaba a
    # presentar "pocas amarillas" como una fortaleza de Pedri, por delante de
    # sus pases clave.
    Metric("yellow_cards", "player_season", "yellow_cards", "Tarjetas amarillas",
           higher_is_better=None, source="understat"),
    Metric("red_cards", "player_season", "red_cards", "Tarjetas rojas",
           higher_is_better=None, source="understat"),
)
# fmt: on


# ---------------------------------------------------------------------------
# Equipos
# ---------------------------------------------------------------------------

# Se cargan dos filas por equipo y temporada: lo que hace el equipo
# (perspective="for") y lo que le hacen (perspective="against").
# fmt: off
TEAM_METRICS: tuple[Metric, ...] = (
    Metric("matches_played", "team_season", "matches", "Partidos jugados",
           dtype="int", per90=False, higher_is_better=None, source="understat"),
    Metric("goals", "team_season", "goals", "Goles", source="understat"),
    Metric("xg", "team_season", "xg", "xG", source="understat"),
    Metric("np_xg", "team_season", "np_xg", "xG sin penaltis", source="understat"),
    # Pases completados a menos de 20 metros de la porteria: mide cuanto
    # territorio de verdad pisa el equipo, no cuanto balon tiene.
    Metric("deep_completions", "team_season", "deep_completions",
           "Llegadas a zona de remate", source="understat"),
    # PPDA real de Understat, no la aproximacion sobre todo el campo que se
    # derivaba antes. Un valor BAJO significa presion alta: el rival da pocos
    # pases por cada accion defensiva.
    Metric("ppda", "team_season", "ppda", "PPDA",
           higher_is_better=None, per90=False, source="understat"),
)
# fmt: on


def metrics_from(metrics: tuple[Metric, ...], source: str) -> tuple[Metric, ...]:
    """Metricas que vienen de una fuente concreta."""
    return tuple(metric for metric in metrics if metric.source == source)


def stat_types(metrics: tuple[Metric, ...], source: str = "fbref") -> tuple[str, ...]:
    """Tablas que hay que descargar de una fuente para cubrir el catalogo."""
    seen: dict[str, None] = {}
    for metric in metrics_from(metrics, source):
        seen.setdefault(metric.stat_type, None)
    return tuple(seen)


def metrics_by_stat_type(metrics: tuple[Metric, ...], stat_type: str) -> tuple[Metric, ...]:
    """Metricas que provienen de una tabla concreta de FBref."""
    return tuple(metric for metric in metrics if metric.stat_type == stat_type)


def metrics_for_position(metrics: tuple[Metric, ...], position: str) -> tuple[Metric, ...]:
    """Metricas informativas para un grupo de posicion."""
    return tuple(metric for metric in metrics if position in metric.positions)
