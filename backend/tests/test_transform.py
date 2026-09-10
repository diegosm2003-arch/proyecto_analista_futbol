"""Tests de la limpieza de datos de FBref. No requieren red ni base de datos."""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.etl import transform
from futbol_analytics.etl.transform import (
    MissingColumnsError,
    build_player_frame,
    flatten_columns,
    parse_age,
    parse_nation,
    select_metrics,
    slugify,
    to_records,
)
from futbol_analytics.metrics import Metric, metrics_by_stat_type

# Catalogo propio del test. Se prueba la limpieza de tablas de FBref, que sigue
# existiendo aunque el catalogo real haya pasado a Understat: no conviene que
# estos tests dependan de que fuente este activa hoy.
CATALOGO: tuple[Metric, ...] = (
    Metric(
        "minutes",
        "standard",
        "playing_time_min",
        "Minutos",
        dtype="int",
        per90=False,
        higher_is_better=None,
    ),
    Metric("goals", "standard", "performance_gls", "Goles"),
    Metric("assists", "standard", "performance_ast", "Asistencias"),
    Metric("tackles", "defense", "tackles_tkl", "Entradas"),
    Metric(
        "tackles_att_third",
        "defense",
        "tackles_att_3rd",
        "Entradas en campo rival",
        higher_is_better=None,
    ),
    Metric("interceptions", "defense", "int", "Intercepciones"),
    Metric("post_shot_xg", "keeper_adv", "expected_psxg", "PSxG", required=False),
)

INDICE = pd.MultiIndex.from_tuples(
    [
        ("ESP-La Liga", "2526", "Barcelona", "Pedri"),
        ("ESP-La Liga", "2526", "Barcelona", "Cubarsi"),
        ("ESP-La Liga", "2526", "Girona", "Suplente"),
    ],
    names=["league", "season", "team", "player"],
)


def _frame(stat_type: str, overrides: dict[str, list] | None = None) -> pd.DataFrame:
    """Construye una tabla de FBref con las columnas que el catalogo espera.

    Se genera desde el propio catalogo para que el test no se rompa cada vez que
    se anade una metrica: lo que se comprueba es el comportamiento, no la lista.
    """
    metrics = metrics_by_stat_type(CATALOGO, stat_type)
    data: dict[str, list] = {
        metric.column: [float(i + 1) for i in range(len(INDICE))] for metric in metrics
    }
    data.update(overrides or {})
    return pd.DataFrame(data, index=INDICE)


def _standard(overrides: dict[str, list] | None = None) -> pd.DataFrame:
    identidad = {
        "pos": ["MF", "DF", None],
        "nation": ["es ESP", "es ESP", None],
        "age": ["22-104", "18-011", None],
        "born": [2002.0, 2007.0, None],
    }
    identidad.update(overrides or {})
    return _frame("standard", identidad)


# --- Normalizacion de nombres de columna -----------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Playing Time", "playing_time"),
        ("SoT%", "sot_pct"),
        ("Take-Ons", "take_ons"),
        ("1/3", "1_3"),
        ("Att Pen", "att_pen"),
        ("  Gls  ", "gls"),
    ],
)
def test_slugify(entrada: str, esperado: str) -> None:
    assert slugify(entrada) == esperado


def test_flatten_columns_conserva_el_grupo_como_prefijo() -> None:
    # Sin el prefijo hay colision real: en la tabla de defensa, ("Tackles",
    # "Tkl") son entradas y ("Challenges", "Tkl") son regateadores frenados.
    columnas = pd.MultiIndex.from_tuples(
        [("Tackles", "Tkl"), ("Challenges", "Tkl"), ("Unnamed: 8_level_0", "Int")]
    )
    frame = pd.DataFrame([[1, 2, 3]], columns=columnas)

    aplanado = flatten_columns(frame)

    assert list(aplanado.columns) == ["tackles_tkl", "challenges_tkl", "int"]


def test_flatten_columns_descarta_las_columnas_por_90() -> None:
    # Regla de diseno: se persisten totales; el per-90 es cosa del analisis.
    columnas = pd.MultiIndex.from_tuples(
        [("Performance", "Gls"), ("Per 90 Minutes", "Gls"), ("Per 90 Minutes", "xG")]
    )
    frame = pd.DataFrame([[10, 0.5, 0.4]], columns=columnas)

    aplanado = flatten_columns(frame)

    assert list(aplanado.columns) == ["performance_gls"]


def test_flatten_columns_acepta_cabeceras_de_un_solo_nivel() -> None:
    frame = pd.DataFrame([[1]], columns=["Playing Time"])

    assert list(flatten_columns(frame).columns) == ["playing_time"]


# --- Seleccion de metricas --------------------------------------------------


def test_select_metrics_traduce_a_nombres_canonicos() -> None:
    seleccion = select_metrics(_standard(), CATALOGO, "standard")

    assert "minutes" in seleccion.columns
    assert "assists" in seleccion.columns
    # La identidad no es una metrica: se anade por separado.
    assert "pos" not in seleccion.columns


def test_select_metrics_falla_si_falta_una_columna_obligatoria() -> None:
    # Es deliberado: mejor parar que cargar una temporada entera de NULL porque
    # FBref ha renombrado una columna sin avisar.
    frame = _standard().drop(columns=["playing_time_min"])

    with pytest.raises(MissingColumnsError, match="playing_time_min"):
        select_metrics(frame, CATALOGO, "standard")


def test_select_metrics_tolera_la_ausencia_de_una_metrica_opcional() -> None:
    opcional = next(m for m in CATALOGO if not m.required)
    frame = _frame(opcional.stat_type).drop(columns=[opcional.column])

    seleccion = select_metrics(frame, CATALOGO, opcional.stat_type)

    assert seleccion[opcional.name].isna().all()


def test_select_metrics_devuelve_vacio_si_el_stat_type_no_esta_en_el_catalogo() -> None:
    seleccion = select_metrics(_standard(), CATALOGO, "passing_types")

    assert seleccion.empty or list(seleccion.columns) == []


# --- Construccion de la tabla de jugadores ----------------------------------


def test_build_player_frame_deriva_el_grupo_de_posicion() -> None:
    resultado = build_player_frame({"standard": _standard()}, CATALOGO)

    posiciones = dict(zip(resultado["player"], resultado["position_group"], strict=True))
    assert posiciones["Pedri"] == "MF"
    assert posiciones["Cubarsi"] == "DF"
    # Sin posicion reconocible se deja NULL: quedara fuera de los percentiles.
    assert pd.isna(posiciones["Suplente"])


def test_build_player_frame_conserva_la_posicion_cruda_de_fbref() -> None:
    resultado = build_player_frame({"standard": _standard()}, CATALOGO)

    assert set(resultado["position_raw"].dropna()) == {"MF", "DF"}


def test_build_player_frame_no_filtra_por_minutos() -> None:
    # El umbral MIN_MINUTES define la poblacion de percentiles, no lo que existe
    # en la base de datos. Filtrar en el ETL perderia el dato para siempre.
    frame = _standard({"playing_time_min": [2800.0, 1500.0, 12.0]})

    resultado = build_player_frame({"standard": frame}, CATALOGO)

    assert len(resultado) == 3
    assert resultado["minutes"].min() == 12.0


def test_build_player_frame_une_varias_tablas_por_el_indice() -> None:
    resultado = build_player_frame(
        {"standard": _standard(), "defense": _frame("defense")}, CATALOGO
    )

    assert {"minutes", "interceptions", "tackles_att_third"} <= set(resultado.columns)
    assert len(resultado) == 3


def test_build_player_frame_descarta_filas_sin_clave() -> None:
    # FBref deja filas de totales al final de sus tablas, sin jugador.
    indice = pd.MultiIndex.from_tuples(
        [("ESP-La Liga", "2526", "Barcelona", "Pedri"), ("ESP-La Liga", "2526", "Barcelona", None)],
        names=["league", "season", "team", "player"],
    )
    frame = _standard().iloc[:2].copy()
    frame.index = indice

    resultado = build_player_frame({"standard": frame}, CATALOGO)

    assert list(resultado["player"]) == ["Pedri"]


def test_build_player_frame_sin_datos_devuelve_vacio() -> None:
    assert build_player_frame({}, CATALOGO).empty


# --- Utilidades -------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("22-104", 22), ("30", 30), (None, None), ("", None), ("sin edad", None)],
)
def test_parse_age(entrada: object, esperado: int | None) -> None:
    assert parse_age(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("es ESP", "ESP"), ("ESP", "ESP"), (None, None)],
)
def test_parse_nation(entrada: object, esperado: str | None) -> None:
    assert parse_nation(entrada) == esperado


def test_to_records_convierte_los_huecos_en_none() -> None:
    # Un hueco debe ser NULL, no cero: cero afirmaria algo falso sobre el
    # jugador, y ademas PostgreSQL no acepta NaN en columnas enteras.
    frame = pd.DataFrame({"player": ["Pedri"], "goals": [float("nan")]})

    registros = to_records(frame)

    assert registros == [{"player": "Pedri", "goals": None}]


def test_to_records_de_un_frame_vacio() -> None:
    assert to_records(pd.DataFrame()) == []


# --- Tiros individuales -----------------------------------------------------


def _tiros(**columnas) -> pd.DataFrame:
    base = {
        "shot_id": ["1", "2"],
        "league": ["ESP-La Liga"] * 2,
        "season": ["2627"] * 2,
        "game": ["g1"] * 2,
        "game_id": ["29158"] * 2,
        "date": ["2026-08-15", "2026-08-15"],
        "team": ["Barcelona"] * 2,
        "player": ["A", "B"],
        "player_id": ["100", "200"],
        "minute": [10, 20],
        "xg": [0.5, 0.7432776093482971],
        "location_x": [0.7, 0.885],
        "location_y": [0.4, 0.5],
        "body_part": ["Right Foot", None],
        "situation": ["Open Play", None],
        "result": ["Goal", "Goal"],
        "assist_player": ["C", None],
    }
    base.update(columnas)
    frame = pd.DataFrame(base)
    return frame.set_index(["league", "season", "game", "team", "player"])


def test_un_penalti_se_reconoce_aunque_understat_lo_deje_sin_situacion() -> None:
    # Los penaltis llegan con la situacion vacia. Se reconocen sin suponer nada:
    # comparten el punto de lanzamiento exacto, que ninguna otra jugada
    # reproduce. Sin la etiqueta, el npxG calculado desde los tiros incluiria
    # penaltis en silencio.
    filas = transform.build_shot_frame(_tiros())

    situaciones = dict(zip(filas["shot_id"], filas["situation"], strict=True))
    assert situaciones["1"] == "Open Play"
    assert situaciones["2"] == "Penalty"


def test_un_tiro_fuera_del_punto_de_penalti_no_se_etiqueta() -> None:
    # Un tiro sin situacion desde otro sitio se queda sin ella: es mejor un
    # hueco que una etiqueta inventada.
    filas = transform.build_shot_frame(_tiros(location_x=[0.7, 0.6], location_y=[0.4, 0.3]))

    assert filas[filas["shot_id"] == "2"]["situation"].iloc[0] is None


def test_el_identificador_de_jugador_viaja_con_el_tiro() -> None:
    # Es el mismo puente que usa player_season: sin el habria que cruzar por
    # nombre otra vez.
    filas = transform.build_shot_frame(_tiros())

    assert set(filas["understat_id"]) == {"100", "200"}


def test_un_tiro_repetido_no_se_carga_dos_veces() -> None:
    repetidos = _tiros(shot_id=["1", "1"])

    assert len(transform.build_shot_frame(repetidos)) == 1


def test_sin_tiros_no_revienta() -> None:
    assert transform.build_shot_frame(pd.DataFrame()).empty
