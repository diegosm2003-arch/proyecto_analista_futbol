"""Catalogo de metricas.

Es la pieza central de la fase de datos: define QUE se guarda y por que tiene
sentido futbolistico. De este catalogo se generan las columnas de las tablas de
PostgreSQL, asi que esquema y catalogo no pueden divergir.

Dos reglas de diseno:

1. **Se guardan totales, nunca valores por 90 minutos.** El per-90 depende del
   umbral de minutos y de la poblacion de comparacion: es una decision de
   analisis, no un hecho que persistir. Las columnas "Per 90 Minutes" de FBref
   se descartan al cargar.
2. **Se guardan metricas con significado, no todo lo que FBref publica.**
   "Pases totales" sin contexto no dice nada; "pases progresivos" o "toques en
   el ultimo tercio" si.

El campo `column` es el nombre de la columna de FBref ya aplanado por
`etl.transform.flatten_columns` (grupo + estadistico, en snake_case).
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
        possession_sensitive: Si el volumen de la metrica depende de cuanto
            tiempo pasa el equipo sin balon. Un pivote de un equipo que domina
            tiene menos ocasiones de entrar que uno de un equipo replegado, asi
            que su valor por 90 mide al equipo tanto como al jugador. Estas
            metricas se ofrecen tambien ajustadas por posesion.
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
    possession_sensitive: bool = False


# ---------------------------------------------------------------------------
# Jugadores
# ---------------------------------------------------------------------------

PLAYER_METRICS: tuple[Metric, ...] = (
    # --- Volumen de juego. No son metricas de rendimiento: son el denominador.
    Metric("matches_played", "standard", "playing_time_mp", "Partidos jugados",
           dtype="int", per90=False, higher_is_better=None),
    Metric("starts", "standard", "playing_time_starts", "Titularidades",
           dtype="int", per90=False, higher_is_better=None),
    Metric("minutes", "standard", "playing_time_min", "Minutos",
           dtype="int", per90=False, higher_is_better=None),

    # --- Produccion ofensiva.
    Metric("goals", "standard", "performance_gls", "Goles", positions=OUTFIELD),
    Metric("assists", "standard", "performance_ast", "Asistencias", positions=OUTFIELD),
    # npxG separa el merito del juego del merito de tirar penaltis, que dice mas
    # de quien es el designado que del rendimiento del jugador.
    Metric("npxg", "standard", "expected_npxg", "xG sin penaltis", positions=OUTFIELD),
    Metric("xg", "standard", "expected_xg", "xG", positions=OUTFIELD),
    Metric("xag", "standard", "expected_xag", "xAG (goles esperados asistidos)",
           positions=OUTFIELD),

    # --- Progresion: mover el balon hacia la porteria rival.
    Metric("progressive_carries", "standard", "progression_prgc",
           "Conducciones progresivas", positions=OUTFIELD),
    Metric("progressive_passes", "standard", "progression_prgp",
           "Pases progresivos", positions=OUTFIELD),
    Metric("progressive_passes_received", "standard", "progression_prgr",
           "Pases progresivos recibidos", positions=OUTFIELD),

    # --- Tiro.
    Metric("shots", "shooting", "standard_sh", "Tiros", positions=OUTFIELD),
    Metric("shots_on_target", "shooting", "standard_sot", "Tiros a puerta",
           positions=OUTFIELD),
    # La distancia media de tiro no es mejor alta ni baja: describe el perfil.
    Metric("avg_shot_distance", "shooting", "standard_dist", "Distancia media de tiro",
           positions=OUTFIELD, higher_is_better=None, per90=False),

    # --- Pase.
    Metric("passes_completed", "passing", "total_cmp", "Pases completados",
           positions=OUTFIELD),
    Metric("passes_attempted", "passing", "total_att", "Pases intentados",
           positions=OUTFIELD, higher_is_better=None),
    Metric("progressive_pass_distance", "passing", "total_prgdist",
           "Distancia progresiva de pase", positions=OUTFIELD),
    Metric("key_passes", "passing", "kp", "Pases clave", positions=OUTFIELD),
    Metric("passes_into_final_third", "passing", "1_3", "Pases al ultimo tercio",
           positions=OUTFIELD),
    Metric("passes_into_penalty_area", "passing", "ppa", "Pases al area",
           positions=OUTFIELD),
    Metric("crosses_into_penalty_area", "passing", "crspa", "Centros al area",
           positions=OUTFIELD),
    Metric("xa", "passing", "expected_xa", "xA (asistencias esperadas)",
           positions=OUTFIELD),

    # --- Creacion: acciones que terminan en tiro o en gol.
    Metric("shot_creating_actions", "goal_shot_creation", "sca_sca",
           "Acciones que generan tiro", positions=OUTFIELD),
    Metric("goal_creating_actions", "goal_shot_creation", "gca_gca",
           "Acciones que generan gol", positions=OUTFIELD),

    # --- Defensa. El reparto por tercios describe la altura de la presion, que
    #     es informacion de estilo y no de calidad: higher_is_better=None.
    #     Todas son sensibles a la posesion: sin ajustar, el jugador del equipo
    #     que menos balon tiene sale sistematicamente mejor, y eso mide al
    #     equipo, no al jugador.
    Metric("tackles", "defense", "tackles_tkl", "Entradas",
           positions=OUTFIELD, possession_sensitive=True),
    Metric("tackles_won", "defense", "tackles_tklw", "Entradas ganadas",
           positions=OUTFIELD, possession_sensitive=True),
    Metric("tackles_def_third", "defense", "tackles_def_3rd",
           "Entradas en tercio defensivo", positions=OUTFIELD,
           higher_is_better=None, possession_sensitive=True),
    Metric("tackles_mid_third", "defense", "tackles_mid_3rd",
           "Entradas en tercio medio", positions=OUTFIELD,
           higher_is_better=None, possession_sensitive=True),
    Metric("tackles_att_third", "defense", "tackles_att_3rd",
           "Entradas en tercio ofensivo", positions=OUTFIELD,
           higher_is_better=None, possession_sensitive=True),
    Metric("dribblers_challenged", "defense", "challenges_att",
           "Regateadores desafiados", positions=OUTFIELD,
           higher_is_better=None, possession_sensitive=True),
    Metric("dribblers_tackled", "defense", "challenges_tkl",
           "Regateadores frenados", positions=OUTFIELD, possession_sensitive=True),
    Metric("blocks", "defense", "blocks_blocks", "Bloqueos",
           positions=OUTFIELD, possession_sensitive=True),
    Metric("interceptions", "defense", "int", "Intercepciones",
           positions=OUTFIELD, possession_sensitive=True),
    Metric("clearances", "defense", "clr", "Despejes",
           positions=("DF", "MF"), higher_is_better=None, possession_sensitive=True),

    # --- Posesion. Los toques por zona son la base para separar roles (central
    #     vs lateral, interior vs extremo) en el clustering de la fase 3, que es
    #     justo lo que FBref no da como posicion detallada.
    Metric("touches", "possession", "touches_touches", "Toques", higher_is_better=None),
    Metric("touches_def_third", "possession", "touches_def_3rd",
           "Toques en tercio defensivo", higher_is_better=None),
    Metric("touches_mid_third", "possession", "touches_mid_3rd",
           "Toques en tercio medio", higher_is_better=None),
    Metric("touches_att_third", "possession", "touches_att_3rd",
           "Toques en tercio ofensivo", higher_is_better=None),
    Metric("touches_att_pen", "possession", "touches_att_pen", "Toques en area rival",
           positions=OUTFIELD, higher_is_better=None),
    Metric("take_ons_attempted", "possession", "take_ons_att", "Regates intentados",
           positions=OUTFIELD, higher_is_better=None),
    Metric("take_ons_successful", "possession", "take_ons_succ", "Regates completados",
           positions=OUTFIELD),
    Metric("carries", "possession", "carries_carries", "Conducciones",
           higher_is_better=None),
    Metric("carries_into_final_third", "possession", "carries_1_3",
           "Conducciones al ultimo tercio", positions=OUTFIELD),
    Metric("carries_into_penalty_area", "possession", "carries_cpa",
           "Conducciones al area", positions=OUTFIELD),
    Metric("passes_received", "possession", "receiving_rec", "Pases recibidos",
           positions=OUTFIELD, higher_is_better=None),

    # --- Duelos y recuperaciones. Los duelos aereos NO se marcan como sensibles
    #     a la posesion: dependen sobre todo de si el rival juega en largo, que
    #     es otra cosa distinta a cuanto balon tiene el equipo propio.
    Metric("aerials_won", "misc", "aerial_duels_won", "Duelos aereos ganados"),
    Metric("aerials_lost", "misc", "aerial_duels_lost", "Duelos aereos perdidos",
           higher_is_better=None),
    Metric("ball_recoveries", "misc", "performance_recov", "Recuperaciones",
           higher_is_better=None, possession_sensitive=True),
    Metric("fouls_committed", "misc", "performance_fls", "Faltas cometidas",
           higher_is_better=False),

    # --- Porteros.
    Metric("goals_against", "keeper", "performance_ga", "Goles encajados",
           positions=("GK",), higher_is_better=False),
    Metric("saves", "keeper", "performance_saves", "Paradas", positions=("GK",)),
    # PSxG menos goles encajados es la mejor medida publica de si un portero
    # para mas de lo esperado dado el tiro que recibe.
    Metric("post_shot_xg", "keeper_adv", "expected_psxg", "PSxG",
           positions=("GK",), higher_is_better=None, required=False),
)


# ---------------------------------------------------------------------------
# Equipos
# ---------------------------------------------------------------------------

# Se cargan dos filas por equipo y temporada: lo que hace el equipo
# (perspective="for") y lo que le hacen (perspective="against"). Con ambas se
# pueden derivar en la fase de analisis indicadores de estilo como una PPDA
# aproximada: pases del rival por accion defensiva propia.
TEAM_METRICS: tuple[Metric, ...] = (
    Metric("matches_played", "standard", "playing_time_mp", "Partidos jugados",
           dtype="int", per90=False, higher_is_better=None),
    Metric("minutes", "standard", "playing_time_min", "Minutos",
           dtype="int", per90=False, higher_is_better=None),
    Metric("goals", "standard", "performance_gls", "Goles"),
    Metric("xg", "standard", "expected_xg", "xG"),
    Metric("npxg", "standard", "expected_npxg", "xG sin penaltis"),
    Metric("progressive_passes", "standard", "progression_prgp", "Pases progresivos"),
    Metric("progressive_carries", "standard", "progression_prgc",
           "Conducciones progresivas"),
    Metric("shots", "shooting", "standard_sh", "Tiros"),
    Metric("shots_on_target", "shooting", "standard_sot", "Tiros a puerta"),
    Metric("passes_completed", "passing", "total_cmp", "Pases completados"),
    Metric("passes_attempted", "passing", "total_att", "Pases intentados",
           higher_is_better=None),
    Metric("passes_into_final_third", "passing", "1_3", "Pases al ultimo tercio"),
    Metric("tackles", "defense", "tackles_tkl", "Entradas", higher_is_better=None),
    Metric("tackles_att_third", "defense", "tackles_att_3rd",
           "Entradas en tercio ofensivo", higher_is_better=None),
    Metric("interceptions", "defense", "int", "Intercepciones", higher_is_better=None),
    Metric("touches_att_third", "possession", "touches_att_3rd",
           "Toques en tercio ofensivo", higher_is_better=None),
    # Posesion media del equipo. Es la que permite ajustar por posesion las
    # metricas defensivas de sus jugadores. Opcional porque no esta claro en que
    # tabla la publica FBref para todas las temporadas; si falta, el analisis
    # cae en una aproximacion a partir de los pases propios y del rival.
    Metric("possession_pct", "possession", "poss", "Posesion (%)",
           higher_is_better=None, per90=False, required=False),
)


def stat_types(metrics: tuple[Metric, ...]) -> tuple[str, ...]:
    """Tablas de FBref que hay que descargar para cubrir el catalogo."""
    seen: dict[str, None] = {}
    for metric in metrics:
        seen.setdefault(metric.stat_type, None)
    return tuple(seen)


def metrics_by_stat_type(metrics: tuple[Metric, ...], stat_type: str) -> tuple[Metric, ...]:
    """Metricas que provienen de una tabla concreta de FBref."""
    return tuple(metric for metric in metrics if metric.stat_type == stat_type)


def metrics_for_position(metrics: tuple[Metric, ...], position: str) -> tuple[Metric, ...]:
    """Metricas informativas para un grupo de posicion."""
    return tuple(metric for metric in metrics if position in metric.positions)
