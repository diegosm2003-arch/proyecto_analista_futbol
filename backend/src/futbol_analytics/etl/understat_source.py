"""Lectura de Understat.

Understat entro en el proyecto como plan B y acabo siendo imprescindible: FBref
sirve vacias sus tablas avanzadas (comprobado en 2023/24, 2024/25 y 2025/26; las
celdas existen y no traen ningun numero), asi que **toda la familia xG viene de
aqui**.

Lo que aporta y FBref no:

- `xg`, `np_xg`, `xa`: goles y asistencias esperados, que son la base del
  analisis moderno.
- `xg_chain` y `xg_buildup`: reparten el xG de una jugada entre quienes la
  tocaron. `xg_buildup` ademas descuenta el tiro y la asistencia, asi que aisla
  a quien construye sin finalizar. Es la metrica que descubre organizadores que
  ninguna estadistica de conteo refleja.
- `ppda` real por partido, no la aproximacion sobre todo el campo que veniamos
  arrastrando.
- `player_id`, un identificador estable. Hasta ahora la clave era el nombre, que
  se rompe con acentos, cambios de grafia y homonimos.

A diferencia de FBref, Understat se descarga con peticiones HTTP normales: no
hay Cloudflare, ni navegador, ni pantalla virtual. Funciona dentro del
contenedor.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

from futbol_analytics.config import get_settings

logger = logging.getLogger(__name__)

# Understat solo cubre las cinco grandes ligas, con sus propios identificadores.
UNDERSTAT_LEAGUES: dict[str, str] = {
    "ESP-La Liga": "ESP-La Liga",
    "ENG-Premier League": "ENG-Premier League",
    "ITA-Serie A": "ITA-Serie A",
    "GER-Bundesliga": "GER-Bundesliga",
    "FRA-Ligue 1": "FRA-Ligue 1",
}


def supported(leagues: list[str]) -> list[str]:
    """Ligas de las que Understat tiene datos."""
    conocidas = [liga for liga in leagues if liga in UNDERSTAT_LEAGUES]
    ignoradas = [liga for liga in leagues if liga not in UNDERSTAT_LEAGUES]
    if ignoradas:
        logger.warning("Ligas sin datos en Understat", extra={"ligas": ignoradas})
    return conocidas


def _understat(leagues: list[str], seasons: list[str]) -> Any:
    """Crea el lector de Understat.

    El import es perezoso y `SOCCERDATA_DIR` se fija antes, por lo mismo que en
    FBref: la libreria decide donde cachear al importarse.
    """
    settings = get_settings()
    os.environ.setdefault("SOCCERDATA_DIR", settings.soccerdata_dir)

    import soccerdata

    return soccerdata.Understat(leagues=leagues, seasons=seasons)


def read_player_season_stats(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Estadisticas de temporada por jugador.

    Devuelve el indice (liga, temporada, equipo, jugador), el mismo que usa el
    resto del ETL, asi que se une con lo de FBref sin traduccion.
    """
    settings = get_settings()
    ligas = supported(leagues or settings.leagues)
    temporadas = seasons or settings.seasons

    if not ligas:
        logger.warning("Ninguna liga pedida esta en Understat")
        return pd.DataFrame()

    logger.info(
        "Descargando jugadores de Understat",
        extra={"ligas": ligas, "temporadas": temporadas},
    )
    frame = _understat(ligas, temporadas).read_player_season_stats()
    logger.info("Understat descargado", extra={"filas": len(frame)})
    return frame


def read_shot_events(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Tiros individuales, uno por fila.

    Es el dato que separa "este jugador genera 0,35 npxG por 90" de "desde donde
    tira y con que calidad". Trae coordenadas, el xG de ESE tiro, la parte del
    cuerpo, el resultado y —lo mas infrautilizado— la situacion de la que nace:
    jugada, corner, falta directa o balon parado en general.

    El `player_id` que devuelve Understat es el mismo identificador que ya usa
    `player_season`, asi que los tiros se unen a un jugador sin cruzar nombres.
    """
    settings = get_settings()
    ligas = supported(leagues or settings.leagues)
    temporadas = seasons or settings.seasons

    if not ligas:
        logger.warning("Ninguna liga pedida esta en Understat")
        return pd.DataFrame()

    logger.info(
        "Descargando tiros de Understat",
        extra={"ligas": ligas, "temporadas": temporadas},
    )
    frame = _understat(ligas, temporadas).read_shot_events()
    logger.info("Tiros descargados", extra={"filas": len(frame)})
    return frame


def read_player_match_stats(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Estadisticas de cada jugador en cada partido.

    Resuelve la limitacion estructural del proyecto: con datos agregados por
    temporada no hay evolucion posible, porque dos temporadas son dos puntos y
    dos puntos no son una tendencia. Por jornada si la hay, y ademas permite
    distinguir dos preguntas que no son la misma: como va la temporada y como
    esta ahora.

    Trae tambien la posicion que jugo cada dia, que no es la de la temporada:
    con eso se ven los cambios de rol tras un cambio de entrenador.
    """
    settings = get_settings()
    ligas = supported(leagues or settings.leagues)
    temporadas = seasons or settings.seasons

    if not ligas:
        logger.warning("Ninguna liga pedida esta en Understat")
        return pd.DataFrame()

    logger.info(
        "Descargando partidos de Understat",
        extra={"ligas": ligas, "temporadas": temporadas},
    )
    frame = _understat(ligas, temporadas).read_player_match_stats()
    logger.info("Partidos descargados", extra={"filas": len(frame)})
    return frame


def read_team_season_stats(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Agrega los partidos de Understat a temporada, por equipo.

    Understat publica por partido y con perspectiva de local y visitante. Aqui
    se apila para que cada equipo tenga una fila con lo suyo, se sumen los
    totales y se promedie la PPDA.

    La PPDA se promedia y no se suma porque es un ratio: sumar "pases del rival
    por accion defensiva" de 38 partidos no significa nada.
    """
    settings = get_settings()
    ligas = supported(leagues or settings.leagues)
    temporadas = seasons or settings.seasons

    if not ligas:
        return pd.DataFrame()

    partidos = _understat(ligas, temporadas).read_team_match_stats().reset_index()

    piezas, piezas_contra = [], []
    for lado in ("home", "away"):
        pieza = partidos[
            [
                "league",
                "season",
                f"{lado}_team",
                f"{lado}_xg",
                f"{lado}_np_xg",
                f"{lado}_ppda",
                f"{lado}_deep_completions",
                f"{lado}_goals",
            ]
        ].copy()
        pieza.columns = [
            "league",
            "season",
            "team",
            "xg",
            "np_xg",
            "ppda",
            "deep_completions",
            "goals",
        ]
        piezas.append(pieza)

    # Y ahora lo que le hacen: en cada partido, lo del rival atribuido a este
    # equipo. Sin esta perspectiva no se puede medir ni lo que concede ni cuanto
    # le presionan a el.
    for lado, rival in (("home", "away"), ("away", "home")):
        pieza = partidos[
            [
                "league",
                "season",
                f"{lado}_team",
                f"{rival}_xg",
                f"{rival}_np_xg",
                f"{rival}_ppda",
                f"{rival}_deep_completions",
                f"{rival}_goals",
            ]
        ].copy()
        pieza.columns = [
            "league",
            "season",
            "team",
            "xg",
            "np_xg",
            "ppda",
            "deep_completions",
            "goals",
        ]
        pieza["perspective"] = "against"
        piezas_contra.append(pieza)

    apilado = pd.concat(piezas, ignore_index=True)

    def _agrupar(frame: pd.DataFrame, perspectiva: str) -> pd.DataFrame:
        resultado = frame.groupby(["league", "season", "team"]).agg(
            xg=("xg", "sum"),
            np_xg=("np_xg", "sum"),
            goals=("goals", "sum"),
            deep_completions=("deep_completions", "sum"),
            # Promedio, no suma: la PPDA es un ratio.
            ppda=("ppda", "mean"),
            matches=("xg", "size"),
        )
        resultado["perspective"] = perspectiva
        return resultado

    a_favor = _agrupar(apilado, "for")
    en_contra = _agrupar(pd.concat(piezas_contra, ignore_index=True), "against")
    agregado = pd.concat([a_favor, en_contra])
    logger.info("Equipos de Understat agregados", extra={"filas": len(agregado)})
    return agregado
