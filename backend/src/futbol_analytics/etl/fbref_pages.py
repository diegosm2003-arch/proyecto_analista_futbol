"""Lector de las tablas avanzadas de FBref que `soccerdata` no expone.

`soccerdata` solo lee la pagina de la competicion, que trae cinco tablas de
equipo: standard, keeper, shooting, playing_time y misc. Con eso se pueden
contar goles, asistencias y minutos, pero no se puede hacer analisis de futbol:
faltan los pases progresivos, los toques por zona del campo, las entradas por
tercio y las acciones que generan tiro. Son justo las metricas que distinguen a
un central de construccion de uno de area, y las que alimentan el clustering de
roles.

FBref si publica esas tablas, cada una en su propia URL
(`/passing/`, `/possession/`, `/defense/`, `/gca/`). Este modulo las descarga y
las devuelve con la misma forma que `soccerdata`, para que el resto del ETL no
note la diferencia.

**Se reutiliza el lector de soccerdata para descargar**, no para parsear: es
quien sabe pasar Cloudflare, respetar el limite de una peticion cada 7 segundos
y cachear en disco. Reescribir eso seria repetir la parte dificil y fragil.
"""

from __future__ import annotations

import logging
from io import StringIO
from typing import TYPE_CHECKING, Any

import pandas as pd
from lxml import etree, html

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

FBREF = "https://fbref.com"

# Identificadores de competicion de FBref y el fragmento que usa en la URL. Se
# fijan aqui porque la busqueda de temporadas de soccerdata no funciona contra
# la estructura actual del sitio, y estos valores son estables desde hace anos.
FBREF_COMPS: dict[str, tuple[int, str]] = {
    "ESP-La Liga": (12, "La-Liga"),
    "ENG-Premier League": (9, "Premier-League"),
    "ITA-Serie A": (11, "Serie-A"),
    "GER-Bundesliga": (20, "Bundesliga"),
    "FRA-Ligue 1": (13, "Ligue-1"),
}

# Tablas que FBref sirve en su propia pagina, con el fragmento de URL que usa.
# `standard` incluye xG y progresion, que no aparecen en la tabla de equipos que
# lee soccerdata.
PAGES: dict[str, str] = {
    "standard": "stats",
    "shooting": "shooting",
    "passing": "passing",
    "passing_types": "passing_types",
    "goal_shot_creation": "gca",
    "defense": "defense",
    "possession": "possession",
    "misc": "misc",
    "keeper": "keepers",
    "keeper_adv": "keepersadv",
}

# El identificador de la tabla de jugadores dentro de cada pagina. FBref usa el
# nombre corto de la tabla, que no siempre coincide con el de la URL.
TABLE_IDS: dict[str, str] = {
    "standard": "stats_standard",
    "shooting": "stats_shooting",
    "passing": "stats_passing",
    "passing_types": "stats_passing_types",
    "goal_shot_creation": "stats_gca",
    "defense": "stats_defense",
    "possession": "stats_possession",
    "misc": "stats_misc",
    "keeper": "stats_keeper",
    "keeper_adv": "stats_keeper_adv",
}


# Fraccion minima de filas con algun dato para dar una tabla por buena. Una
# descarga incompleta trae la identidad de los jugadores pero las celdas de
# estadisticas vacias, y eso pasa por una carga correcta: 611 filas insertadas,
# ETL en verde y todas las metricas a NULL.
MIN_FILL_RATE = 0.5


class PageNotAvailableError(RuntimeError):
    """FBref no ha servido la tabla de jugadores de esa pagina."""


class IncompletePageError(RuntimeError):
    """La tabla ha llegado con las celdas de estadisticas vacias.

    Es el fallo mas peligroso del scraping porque no parece un fallo: la tabla
    existe, tiene el numero de filas correcto y los nombres de los jugadores
    estan bien. Solo faltan los numeros.
    """


def season_to_fbref(season: str) -> str:
    """Convierte el codigo corto de temporada al formato de las URLs de FBref.

    >>> season_to_fbref("2526")
    '2025-2026'
    >>> season_to_fbref("9900")
    '1999-2000'
    """
    if len(season) != 4 or not season.isdigit():
        raise ValueError(f"Codigo de temporada invalido: {season!r}. Se espera algo como '2526'.")

    inicio, fin = int(season[:2]), int(season[2:])
    # Dos digitos no dicen el siglo. Se asume que un codigo por encima de 50 es
    # del siglo XX: FBref no tiene datos anteriores a los anos 80.
    siglo_inicio = 1900 if inicio >= 50 else 2000
    siglo_fin = 1900 if fin >= 50 else 2000
    return f"{siglo_inicio + inicio}-{siglo_fin + fin}"


def build_url(league: str, season: str, stat_type: str) -> str:
    """URL de la pagina de FBref que contiene una tabla concreta.

    >>> build_url("ESP-La Liga", "2526", "passing")
    'https://fbref.com/en/comps/12/2025-2026/passing/2025-2026-La-Liga-Stats'
    """
    if league not in FBREF_COMPS:
        raise ValueError(f"Liga sin identificador de FBref: {league!r}.")
    if stat_type not in PAGES:
        raise ValueError(f"Tabla desconocida: {stat_type!r}. Conocidas: {sorted(PAGES)}.")

    comp_id, slug = FBREF_COMPS[league]
    temporada = season_to_fbref(season)
    return f"{FBREF}/en/comps/{comp_id}/{temporada}/{PAGES[stat_type]}/{temporada}-{slug}-Stats"


def cache_filename(league: str, season: str, stat_type: str) -> str:
    """Nombre del fichero de cache. Unico por liga, temporada y tabla.

    Importa mas de lo que parece: con nombres que colisionan, la segunda
    descarga devuelve la primera pagina y el analisis sale mal sin dar ningun
    error.
    """
    return f"players_{league}_{season}_{stat_type}.html"


def extract_player_table(page: bytes | str, stat_type: str) -> pd.DataFrame:
    """Saca la tabla de jugadores del HTML de una pagina de FBref.

    FBref esconde algunas tablas dentro de comentarios HTML para cargarlas en
    diferido, y otras las sirve directamente. Se prueban las dos formas porque
    varia segun la pagina.
    """
    tabla_id = TABLE_IDS[stat_type]
    arbol = html.parse(StringIO(page) if isinstance(page, str) else page)

    encontradas = arbol.xpath(f"//table[starts-with(@id, '{tabla_id}')]")
    if not encontradas:
        parser = etree.HTMLParser(recover=True)
        for comentario in arbol.xpath(f"//comment()[contains(., '{tabla_id}')]"):
            dentro = etree.fromstring(comentario.text, parser).xpath(
                f"//table[starts-with(@id, '{tabla_id}')]"
            )
            if dentro:
                encontradas = dentro
                break

    if not encontradas:
        raise PageNotAvailableError(
            f"FBref no ha servido la tabla '{tabla_id}'. Puede que la pagina haya cambiado "
            "o que la descarga se quedase incompleta."
        )

    crudo = etree.tostring(encontradas[0], encoding="unicode")
    (frame,) = pd.read_html(StringIO(crudo))
    return frame


def tidy(frame: pd.DataFrame, league: str, season: str) -> pd.DataFrame:
    """Deja la tabla con la misma forma que devuelve `soccerdata`.

    Indice (liga, temporada, equipo, jugador) y cabecera de dos niveles, que es
    lo que espera `transform.flatten_columns`. Asi el resto del ETL no distingue
    de donde vino la tabla.
    """
    limpio = frame.copy()

    # FBref repite la cabecera cada 25 filas para que se pueda leer sin volver
    # arriba. Esas filas no son jugadores.
    columna_jugador = _find_column(limpio, "Player")
    limpio = limpio[limpio[columna_jugador] != "Player"]
    limpio = limpio[limpio[columna_jugador].notna()]

    columna_equipo = _find_column(limpio, "Squad")
    jugadores = limpio[columna_jugador].astype("string")
    equipos = limpio[columna_equipo].astype("string")

    # Se sobran las columnas de identidad, que pasan al indice, y las de
    # navegacion de la web. El resto se conserva con su cabecera de dos niveles.
    fuera = [columna_jugador, columna_equipo]
    for sobra in ("Rk", "Matches"):
        columna = _find_column(limpio, sobra, obligatoria=False)
        if columna is not None:
            fuera.append(columna)
    limpio = limpio.drop(columns=fuera)

    # El indice se construye a mano y no con `set_index`: con cabecera de dos
    # niveles no se pueden anadir columnas de un solo nivel para luego
    # indexarlas.
    limpio.index = pd.MultiIndex.from_arrays(
        [[league] * len(limpio), [season] * len(limpio), equipos, jugadores],
        names=["league", "season", "team", "player"],
    )
    return limpio.sort_index()


def _find_column(frame: pd.DataFrame, nombre: str, obligatoria: bool = True) -> Any:
    """Localiza una columna sin depender de cuantos niveles tenga la cabecera."""
    for columna in frame.columns:
        etiquetas = columna if isinstance(columna, tuple) else (columna,)
        if any(str(parte).strip() == nombre for parte in etiquetas):
            return columna
    if obligatoria:
        raise PageNotAvailableError(f"La tabla no tiene columna {nombre!r}.")
    return None


def fill_rate(frame: pd.DataFrame) -> float:
    """Fraccion de filas con algun dato en las columnas de estadisticas.

    Solo se miran las columnas que cuelgan de un grupo con nombre ("Total",
    "Touches", "Tackles"...). Las de identidad (nacionalidad, edad, ano de
    nacimiento) se excluyen a proposito: vienen en el HTML inicial y estan
    completas aunque no haya llegado ni un solo numero, asi que enmascararian
    justo lo que se quiere detectar.
    """
    if frame.empty:
        return 0.0

    de_estadistica = [
        columna
        for columna in frame.columns
        if isinstance(columna, tuple) and columna[0] and not str(columna[0]).startswith("Unnamed")
    ]
    if not de_estadistica:
        return 0.0

    numeros = frame[de_estadistica].apply(pd.to_numeric, errors="coerce")
    return float(numeros.notna().any(axis=1).mean())


def check_complete(frame: pd.DataFrame, stat_type: str, league: str, season: str) -> None:
    """Rechaza una tabla que ha llegado sin datos.

    Raises:
        IncompletePageError: Si casi ninguna fila trae numeros.
    """
    tasa = fill_rate(frame)
    if tasa < MIN_FILL_RATE:
        raise IncompletePageError(
            f"La tabla '{stat_type}' de {league} {season} ha llegado incompleta: solo el "
            f"{tasa:.1%} de las filas trae datos. La pagina se capturo antes de terminar de "
            "cargar. Borra el fichero del cache y vuelve a descargarla."
        )
    logger.info(
        "Tabla completa",
        extra={"tabla": stat_type, "liga": league, "temporada": season, "relleno": round(tasa, 3)},
    )


def read_stat_type(
    reader: Any,
    leagues: list[str],
    seasons: list[str],
    stat_type: str,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """Descarga y devuelve una tabla para todas las ligas y temporadas pedidas.

    `reader` es un `soccerdata.FBref` ya construido: se usa solo su metodo
    `get`, que descarga pasando por Cloudflare, respeta el limite de peticiones
    y cachea en disco.
    """
    destino = data_dir if data_dir is not None else reader.data_dir
    piezas = []

    for league in leagues:
        for season in seasons:
            url = build_url(league, season, stat_type)
            fichero = destino / cache_filename(league, season, stat_type)
            logger.info(
                "Descargando tabla de FBref",
                extra={"liga": league, "temporada": season, "tabla": stat_type},
            )
            pagina = reader.get(url, fichero)
            limpio = tidy(extract_player_table(pagina, stat_type), league, season)
            check_complete(limpio, stat_type, league, season)
            piezas.append(limpio)

    if not piezas:
        return pd.DataFrame()
    return pd.concat(piezas).sort_index()


# ---------------------------------------------------------------------------
# Tablas de equipo
# ---------------------------------------------------------------------------
#
# La misma pagina que trae la tabla de jugadores trae dos de equipo: lo que el
# equipo hace y lo que le hacen. La segunda es la que permite derivar cualquier
# indicador que dependa del rival, empezando por la presion.


def squad_table_id(stat_type: str, opponent: bool) -> str:
    """Identificador de la tabla de equipo dentro de la pagina.

    >>> squad_table_id("passing", opponent=False)
    'stats_squads_passing_for'
    >>> squad_table_id("passing", opponent=True)
    'stats_squads_passing_against'
    """
    if stat_type not in TABLE_IDS:
        raise ValueError(f"Tabla desconocida: {stat_type!r}. Conocidas: {sorted(TABLE_IDS)}.")
    token = TABLE_IDS[stat_type].removeprefix("stats_")
    return f"stats_squads_{token}_{'against' if opponent else 'for'}"


def squad_cache_filename(league: str, season: str, stat_type: str) -> str:
    """Las tablas de equipo viven en la misma pagina que las de jugador."""
    return cache_filename(league, season, stat_type)


def extract_squad_table(page: bytes | str, stat_type: str, opponent: bool) -> pd.DataFrame:
    """Saca del HTML la tabla de equipo, a favor o en contra."""
    tabla_id = squad_table_id(stat_type, opponent)
    arbol = html.parse(StringIO(page) if isinstance(page, str) else page)

    encontradas = arbol.xpath(f"//table[@id='{tabla_id}']")
    if not encontradas:
        parser = etree.HTMLParser(recover=True)
        for comentario in arbol.xpath(f"//comment()[contains(., '{tabla_id}')]"):
            dentro = etree.fromstring(comentario.text, parser).xpath(f"//table[@id='{tabla_id}']")
            if dentro:
                encontradas = dentro
                break

    if not encontradas:
        raise PageNotAvailableError(f"FBref no ha servido la tabla de equipo '{tabla_id}'.")

    crudo = etree.tostring(encontradas[0], encoding="unicode")
    (frame,) = pd.read_html(StringIO(crudo))
    return frame


def tidy_squad(frame: pd.DataFrame, league: str, season: str) -> pd.DataFrame:
    """Deja la tabla de equipo con indice (liga, temporada, equipo)."""
    limpio = frame.copy()
    columna_equipo = _find_column(limpio, "Squad")

    limpio = limpio[limpio[columna_equipo].notna()]
    limpio = limpio[limpio[columna_equipo] != "Squad"]
    equipos = limpio[columna_equipo].astype("string")

    fuera = [columna_equipo]
    for sobra in ("Rk", "Matches"):
        columna = _find_column(limpio, sobra, obligatoria=False)
        if columna is not None:
            fuera.append(columna)
    limpio = limpio.drop(columns=fuera)

    limpio.index = pd.MultiIndex.from_arrays(
        [[league] * len(limpio), [season] * len(limpio), equipos],
        names=["league", "season", "team"],
    )
    return limpio.sort_index()


def read_team_stat_type(
    reader: Any,
    leagues: list[str],
    seasons: list[str],
    stat_type: str,
    opponent: bool = False,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """Descarga la tabla de equipo de una liga y temporada.

    Comparte pagina y cache con la de jugadores: pedir las dos perspectivas no
    cuesta ninguna peticion extra a FBref, que limita a una cada 7 segundos.
    """
    destino = data_dir if data_dir is not None else reader.data_dir
    piezas = []

    for league in leagues:
        for season in seasons:
            url = build_url(league, season, stat_type)
            fichero = destino / squad_cache_filename(league, season, stat_type)
            pagina = reader.get(url, fichero)
            piezas.append(
                tidy_squad(extract_squad_table(pagina, stat_type, opponent), league, season)
            )

    if not piezas:
        return pd.DataFrame()
    return pd.concat(piezas).sort_index()
