"""Limpieza y normalizacion de lo que devuelve FBref.

Todo lo de este modulo son funciones puras sobre DataFrames: ni red, ni base de
datos. Es lo que permite testear el ETL sin levantar nada.

FBref devuelve columnas en dos niveles ("Playing Time" / "Min") con nombres que
cambian entre temporadas. La estrategia es aplanar a `snake_case` y traducir a
los nombres canonicos del catalogo, fallando de forma ruidosa si falta una
columna obligatoria: es preferible que el ETL pare a que cargue una temporada
entera de NULL silenciosos.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from futbol_analytics.metrics import Metric, metrics_by_stat_type, metrics_from
from futbol_analytics.positions import is_hybrid, primary_position

logger = logging.getLogger(__name__)

# Columnas de FBref que ya vienen normalizadas por 90 minutos. Se descartan: el
# per-90 se calcula en la capa de analisis, donde se conoce el umbral de minutos
# y la poblacion de comparacion.
PER90_PREFIX = "per_90_minutes"

# Niveles de cabecera vacios que pandas nombra "Unnamed: 3_level_0". El patron
# se compara contra el nombre ya normalizado por `slugify`, o sea
# "unnamed_3_level_0".
_UNNAMED = re.compile(r"^unnamed(_\d+)?(_level(_\d+)?)?$")


class MissingColumnsError(RuntimeError):
    """FBref no ha devuelto columnas que el catalogo da por obligatorias.

    Casi siempre significa que FBref ha renombrado algo. Se arregla en el
    catalogo de metricas, que es el unico sitio donde viven esos nombres.
    """


def slugify(text: object) -> str:
    """Normaliza un nombre de columna de FBref a `snake_case`.

    >>> slugify("Playing Time")
    'playing_time'
    >>> slugify("SoT%")
    'sot_pct'
    >>> slugify("Take-Ons")
    'take_ons'
    >>> slugify("1/3")
    '1_3'
    """
    value = str(text).strip().lower().replace("%", " pct")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Aplana la cabecera de dos niveles de FBref.

    El grupo se conserva como prefijo porque sin el hay colisiones reales: en la
    tabla de defensa, ("Tackles", "Tkl") son entradas totales y
    ("Challenges", "Tkl") son regateadores frenados. Son metricas distintas que
    se llaman igual.
    """
    flat = frame.copy()

    if isinstance(frame.columns, pd.MultiIndex):
        names = []
        for parts in frame.columns:
            slugs = [slugify(part) for part in parts]
            keep = [slug for slug in slugs if slug and not _UNNAMED.match(slug)]
            names.append("_".join(keep) if keep else slugify(parts[-1]))
        flat.columns = names
    else:
        flat.columns = [slugify(name) for name in frame.columns]

    per90 = [name for name in flat.columns if name.startswith(PER90_PREFIX)]
    if per90:
        flat = flat.drop(columns=per90)

    # FBref repite alguna columna entre grupos; nos quedamos con la primera.
    return flat.loc[:, ~flat.columns.duplicated()]


def select_metrics(
    frame: pd.DataFrame,
    metrics: tuple[Metric, ...],
    stat_type: str,
    source: str = "fbref",
) -> pd.DataFrame:
    """Extrae y renombra las metricas de un `stat_type` a nombres canonicos.

    Las metricas opcionales que falten se crean vacias; si falta una obligatoria
    se lanza `MissingColumnsError`.
    """
    wanted = metrics_by_stat_type(metrics_from(metrics, source), stat_type)
    if not wanted:
        return pd.DataFrame(index=frame.index)

    flat = flatten_columns(frame)
    missing_required = [m.column for m in wanted if m.required and m.column not in flat.columns]
    if missing_required:
        raise MissingColumnsError(
            f"FBref no ha devuelto estas columnas obligatorias de '{stat_type}': "
            f"{sorted(missing_required)}. Revisa el catalogo en futbol_analytics.metrics. "
            f"Columnas disponibles: {sorted(flat.columns)}"
        )

    selected = pd.DataFrame(index=flat.index)
    for metric in wanted:
        if metric.column in flat.columns:
            selected[metric.name] = pd.to_numeric(flat[metric.column], errors="coerce")
        else:
            selected[metric.name] = pd.NA
            logger.warning(
                "Metrica opcional ausente",
                extra={"metrica": metric.name, "stat_type": stat_type},
            )
    return selected


def merge_stat_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Une las tablas de FBref por su indice (liga, temporada, equipo, jugador).

    Se usa un `outer join` a proposito: la tabla de porteros solo contiene
    porteros y la de campo puede no contener a alguien que solo aparece en una
    de ellas. Con un `inner join` se perderian filas en silencio.
    """
    if not frames:
        return pd.DataFrame()

    merged: pd.DataFrame | None = None
    for name, frame in frames.items():
        if frame.empty:
            logger.warning("Tabla vacia, se omite", extra={"stat_type": name})
            continue
        merged = frame if merged is None else merged.join(frame, how="outer")
    return merged if merged is not None else pd.DataFrame()


def parse_age(value: object) -> int | None:
    """Convierte la edad de FBref a anos enteros.

    FBref la publica como "27-104" (anos-dias). Nos quedamos con los anos: los
    dias no aportan nada a un analisis de temporada.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    years = text.split("-")[0]
    try:
        return int(float(years))
    except ValueError:
        return None


def parse_nation(value: object) -> str | None:
    """Extrae el codigo de pais de FBref, que viene como "es ESP"."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    tokens = str(value).split()
    return tokens[-1].upper() if tokens else None


def add_identity(frame: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Anade nacionalidad, edad y posicion a partir de la tabla `standard`."""
    flat = flatten_columns(raw)
    result = frame.copy()

    # FBref la llama "pos" y Understat "position". El formato tambien difiere
    # ("DF,MF" frente a "D M S"), pero de eso se encarga `primary_position`.
    columna_posicion = next((c for c in ("pos", "position") if c in flat.columns), None)
    if columna_posicion is not None:
        position_raw = flat[columna_posicion]
    else:
        position_raw = pd.Series(index=flat.index, dtype=object)
    result["position_raw"] = position_raw
    result["position_group"] = position_raw.map(primary_position)
    # El identificador de la fuente viaja con la fila: sin el, cruzar con
    # Transfermarkt u otra fuente exigiria adivinar por nombre.
    result["understat_id"] = (
        flat["player_id"].astype("string") if "player_id" in flat.columns else None
    )
    result["nation"] = flat["nation"].map(parse_nation) if "nation" in flat.columns else None
    result["age"] = flat["age"].map(parse_age) if "age" in flat.columns else None
    result["born"] = (
        pd.to_numeric(flat["born"], errors="coerce").astype("Int64")
        if "born" in flat.columns
        else pd.Series(pd.NA, index=flat.index, dtype="Int64")
    )

    sin_posicion = int(result["position_group"].isna().sum())
    if sin_posicion:
        # No es fatal, pero esos jugadores quedan fuera de todo percentil: sin
        # grupo de posicion no hay poblacion contra la que compararlos.
        logger.warning(
            "Jugadores sin grupo de posicion: quedaran fuera de los percentiles",
            extra={"jugadores": sin_posicion},
        )
    hibridos = int(result["position_raw"].map(is_hybrid).sum())
    logger.info("Jugadores con posicion hibrida", extra={"jugadores": hibridos})

    return result


def build_player_frame(
    frames: dict[str, pd.DataFrame],
    metrics: tuple[Metric, ...],
    understat: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convierte las tablas crudas de FBref en filas listas para `player_season`.

    No se filtra por minutos: el umbral `MIN_MINUTES` define la poblacion de los
    percentiles, no lo que existe en la base de datos. Filtrar aqui perderia
    informacion de forma irreversible.
    """
    selected = {
        stat_type: select_metrics(frame, metrics, stat_type) for stat_type, frame in frames.items()
    }
    if understat is not None and not understat.empty:
        # Understat trae hoy todo el catalogo. Se une por el mismo indice
        # (liga, temporada, equipo, jugador) que usan las tablas de FBref, asi
        # que convivir con ellas no exige ninguna traduccion.
        selected["understat"] = select_metrics(
            understat, metrics, "player_season", source="understat"
        )

    merged = merge_stat_frames(selected)
    if merged.empty:
        return merged

    if "standard" in frames:
        merged = add_identity(merged, frames["standard"])
    elif understat is not None and not understat.empty:
        merged = add_identity(merged, understat)

    result = merged.reset_index()
    result = _normalise_keys(result, ("league", "season", "team", "player"))
    logger.info(
        "Filas de jugador preparadas",
        extra={"filas": len(result), "columnas": len(result.columns)},
    )
    return result


def build_team_frame(
    frames_for: dict[str, pd.DataFrame],
    frames_against: dict[str, pd.DataFrame],
    metrics: tuple[Metric, ...],
) -> pd.DataFrame:
    """Prepara `team_season` con las dos perspectivas apiladas."""
    parts = []
    for perspective, frames in (("for", frames_for), ("against", frames_against)):
        selected = {
            stat_type: select_metrics(frame, metrics, stat_type)
            for stat_type, frame in frames.items()
        }
        merged = merge_stat_frames(selected)
        if merged.empty:
            continue
        merged = merged.reset_index()
        merged["perspective"] = perspective
        parts.append(merged)

    if not parts:
        return pd.DataFrame()

    result = pd.concat(parts, ignore_index=True)
    result = _normalise_keys(result, ("league", "season", "team"))
    logger.info("Filas de equipo preparadas", extra={"filas": len(result)})
    return result


def _normalise_keys(frame: pd.DataFrame, keys: tuple[str, ...]) -> pd.DataFrame:
    """Limpia espacios en las columnas clave y descarta filas sin clave completa.

    Una fila sin equipo o sin jugador no se puede insertar (forman la clave
    primaria) y tampoco significa nada: casi siempre es una fila de totales que
    FBref deja al final de la tabla.
    """
    result = frame.copy()
    for key in keys:
        if key in result.columns:
            result[key] = result[key].astype("string").str.strip()

    present = [key for key in keys if key in result.columns]
    before = len(result)
    result = result.dropna(subset=present)
    result = result[~(result[present] == "").any(axis=1)]
    descartadas = before - len(result)
    if descartadas:
        logger.warning("Filas descartadas por clave incompleta", extra={"filas": descartadas})
    return result


def to_records(frame: pd.DataFrame) -> list[dict]:
    """Convierte el DataFrame en filas para el insert.

    `NaN` pasa a `None`: PostgreSQL no acepta NaN en columnas enteras y, sobre
    todo, un dato ausente debe ser NULL y no un valor.
    """
    if frame.empty:
        return []
    cleaned = frame.astype(object).where(pd.notna(frame), None)
    return cleaned.to_dict(orient="records")


def build_shot_frame(shots: pd.DataFrame) -> pd.DataFrame:
    """Convierte los tiros de Understat en filas de `shot_event`.

    Understat devuelve el partido, el equipo y el jugador en el indice, y todo
    lo demas en columnas. Aqui se aplana y se renombra a los nombres de la
    tabla; no se calcula nada, porque el xG de cada tiro ya viene dado y
    recalcularlo seria inventarselo.

    Las coordenadas se dejan tal cual, normalizadas de 0 a 1: convertirlas a
    metros exigiria suponer las dimensiones del campo, que cambian de estadio a
    estadio, y ninguna vista lo necesita.
    """
    if shots.empty:
        return pd.DataFrame()

    plano = shots.reset_index()
    filas = pd.DataFrame(
        {
            "shot_id": plano["shot_id"].astype("string"),
            "league": plano["league"].astype("string"),
            "season": plano["season"].astype("string"),
            "game_id": plano["game_id"].astype("string"),
            "match_date": pd.to_datetime(plano["date"], errors="coerce").dt.date,
            "team": plano["team"].astype("string"),
            "player": plano["player"].astype("string"),
            # El identificador de Understat, que es el mismo puente que usa
            # `player_season`: los tiros se unen a un jugador sin cruzar nombres.
            "understat_id": plano["player_id"].astype("string"),
            "minute": pd.to_numeric(plano["minute"], errors="coerce").astype("Int64"),
            "xg": pd.to_numeric(plano["xg"], errors="coerce"),
            "location_x": pd.to_numeric(plano["location_x"], errors="coerce"),
            "location_y": pd.to_numeric(plano["location_y"], errors="coerce"),
            "body_part": plano["body_part"].astype("string"),
            "situation": plano["situation"].astype("string"),
            "result": plano["result"].astype("string"),
            "assist_player": plano["assist_player"].astype("string"),
        }
    )

    filas["situation"] = _marcar_penaltis(filas)

    # Un tiro sin identificador no se puede insertar ni volver a encontrar.
    filas = filas.dropna(subset=["shot_id"])
    antes = len(filas)
    filas = filas.drop_duplicates(subset=["shot_id"])
    if len(filas) != antes:
        logger.warning(
            "Tiros repetidos descartados",
            extra={"descartados": antes - len(filas)},
        )

    logger.info("Filas de tiro preparadas", extra={"filas": len(filas)})
    return filas.astype(object).where(pd.notna(filas), None)


# El punto de penalti en las coordenadas normalizadas de Understat. Todos los
# penaltis se lanzan del mismo sitio, asi que la posicion es exacta y no
# aproximada.
_PENALTI_X, _PENALTI_Y = 0.885, 0.5
_TOLERANCIA = 0.005


def _marcar_penaltis(shots: pd.DataFrame) -> pd.Series:
    """Pone "Penalty" en la situacion de los penaltis, que Understat deja vacia.

    No es una suposicion. Los tiros afectados comparten tres cosas a la vez: la
    situacion vacia, el xG identico hasta el ultimo decimal (0,7432776...) y las
    coordenadas exactas del punto de penalti. Ninguna otra jugada reproduce eso.

    Importa porque sin la etiqueta el npxG calculado desde los tiros incluiria
    penaltis en silencio, y "sin penaltis" es justo lo que distingue a esa
    metrica. Los agregados de `player_season` no se ven afectados: alli Understat
    ya publica el npxG por separado.
    """
    en_el_punto = ((shots["location_x"] - _PENALTI_X).abs() <= _TOLERANCIA) & (
        (shots["location_y"] - _PENALTI_Y).abs() <= _TOLERANCIA
    )
    penaltis = shots["situation"].isna() & en_el_punto

    if penaltis.any():
        logger.info("Penaltis identificados", extra={"tiros": int(penaltis.sum())})
    return shots["situation"].mask(penaltis, "Penalty")


# Metricas que se copian tal cual del partido, con su tipo. Se enumeran en lugar
# de tomarlas del catalogo porque el catalogo describe la temporada, y aqui no
# hay percentiles ni valores por 90: son totales de un partido.
_ENTEROS_DE_PARTIDO = (
    "minutes",
    "goals",
    "own_goals",
    "shots",
    "assists",
    "key_passes",
    "yellow_cards",
    "red_cards",
)
_DECIMALES_DE_PARTIDO = ("xg", "xa", "xg_chain", "xg_buildup")


def build_match_frame(matches: pd.DataFrame) -> pd.DataFrame:
    """Convierte los partidos de Understat en filas de `player_match`.

    No agrega nada: una fila por jugador y partido, tal y como llega. Las medias
    moviles y la forma reciente se calculan en la capa de analisis, que es donde
    se pueden cambiar sin volver a descargar nada.
    """
    if matches.empty:
        return pd.DataFrame()

    plano = matches.reset_index()
    filas = pd.DataFrame(
        {
            "game_id": plano["game_id"].astype("string"),
            "understat_id": plano["player_id"].astype("string"),
            "league": plano["league"].astype("string"),
            "season": plano["season"].astype("string"),
            "team": plano["team"].astype("string"),
            "player": plano["player"].astype("string"),
            "match_label": plano["game"].astype("string"),
            "position": plano["position"].astype("string"),
        }
    )
    for columna in _ENTEROS_DE_PARTIDO:
        filas[columna] = pd.to_numeric(plano.get(columna), errors="coerce").astype("Int64")
    for columna in _DECIMALES_DE_PARTIDO:
        filas[columna] = pd.to_numeric(plano.get(columna), errors="coerce")

    # Sin las dos partes de la clave la fila no se puede insertar ni encontrar.
    filas = filas.dropna(subset=["game_id", "understat_id"])
    antes = len(filas)
    filas = filas.drop_duplicates(subset=["game_id", "understat_id"])
    if len(filas) != antes:
        logger.warning("Partidos repetidos descartados", extra={"descartados": antes - len(filas)})

    logger.info("Filas de partido preparadas", extra={"filas": len(filas)})
    return filas.astype(object).where(pd.notna(filas), None)
