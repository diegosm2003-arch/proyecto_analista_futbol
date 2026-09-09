"""Tests del lector de tablas avanzadas de FBref.

No tocan la red: se prueba la construccion de URLs, el nombre del cache y el
parseo, con un fragmento de HTML igual al que sirve FBref.
"""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.etl.fbref_pages import (
    PAGES,
    TABLE_IDS,
    PageNotAvailableError,
    build_url,
    cache_filename,
    extract_player_table,
    season_to_fbref,
    tidy,
)

# Fragmento con la forma real de FBref: cabecera de dos niveles, una fila de
# cabecera repetida a mitad de tabla y la columna "Matches" que sobra.
TABLA = """
<table id="stats_passing">
  <thead>
    <tr><th colspan="2"></th><th colspan="2">Total</th><th colspan="1"></th></tr>
    <tr><th>Player</th><th>Squad</th><th>Cmp</th><th>PrgDist</th><th>Matches</th></tr>
  </thead>
  <tbody>
    <tr><td>Pedri</td><td>Barcelona</td><td>1500</td><td>9000</td><td>Matches</td></tr>
    <tr><td>Player</td><td>Squad</td><td>Cmp</td><td>PrgDist</td><td>Matches</td></tr>
    <tr><td>Cubarsi</td><td>Barcelona</td><td>1800</td><td>12000</td><td>Matches</td></tr>
  </tbody>
</table>
"""

COMENTADA = f"<html><body><!-- {TABLA} --></body></html>"


# --- Temporadas -------------------------------------------------------------


@pytest.mark.parametrize(
    ("corta", "larga"),
    [("2526", "2025-2026"), ("2627", "2026-2027"), ("9900", "1999-2000")],
)
def test_season_to_fbref(corta: str, larga: str) -> None:
    assert season_to_fbref(corta) == larga


def test_season_to_fbref_rechaza_un_codigo_invalido() -> None:
    with pytest.raises(ValueError, match="invalido"):
        season_to_fbref("2025-2026")


# --- URLs -------------------------------------------------------------------


def test_build_url_apunta_a_la_pagina_de_la_tabla() -> None:
    # Comprobada contra FBref: es la URL que devuelve la tabla stats_passing.
    assert build_url("ESP-La Liga", "2526", "passing") == (
        "https://fbref.com/en/comps/12/2025-2026/passing/2025-2026-La-Liga-Stats"
    )


def test_cada_liga_tiene_su_identificador_de_competicion() -> None:
    urls = {build_url(liga, "2526", "passing") for liga in ("ESP-La Liga", "ENG-Premier League")}

    assert len(urls) == 2


def test_build_url_rechaza_una_liga_desconocida() -> None:
    with pytest.raises(ValueError, match="identificador"):
        build_url("POR-Primeira Liga", "2526", "passing")


def test_build_url_rechaza_una_tabla_desconocida() -> None:
    with pytest.raises(ValueError, match="desconocida"):
        build_url("ESP-La Liga", "2526", "inventada")


def test_toda_pagina_declarada_tiene_su_identificador_de_tabla() -> None:
    assert set(PAGES) == set(TABLE_IDS)


# --- Cache ------------------------------------------------------------------


def test_el_nombre_de_cache_distingue_cada_tabla() -> None:
    # Con nombres que colisionan, la segunda descarga devuelve la primera pagina
    # y el analisis sale mal sin dar ningun error. Paso justo eso en el sondeo.
    nombres = {cache_filename("ESP-La Liga", "2526", tabla) for tabla in ("passing", "possession")}

    assert len(nombres) == 2


def test_el_nombre_de_cache_distingue_liga_y_temporada() -> None:
    nombres = {
        cache_filename("ESP-La Liga", "2526", "passing"),
        cache_filename("ESP-La Liga", "2627", "passing"),
        cache_filename("ITA-Serie A", "2526", "passing"),
    }

    assert len(nombres) == 3


# --- Parseo -----------------------------------------------------------------


def test_extrae_la_tabla_servida_directamente() -> None:
    frame = extract_player_table(TABLA, "passing")

    assert len(frame) == 3


def test_extrae_la_tabla_escondida_en_un_comentario() -> None:
    # FBref esconde algunas tablas en comentarios para cargarlas en diferido.
    frame = extract_player_table(COMENTADA, "passing")

    assert len(frame) == 3


def test_si_no_esta_la_tabla_se_dice_claramente() -> None:
    with pytest.raises(PageNotAvailableError, match="stats_passing"):
        extract_player_table("<html><body><p>nada</p></body></html>", "passing")


def test_tidy_deja_el_indice_que_espera_el_resto_del_etl() -> None:
    limpio = tidy(extract_player_table(TABLA, "passing"), "ESP-La Liga", "2526")

    assert list(limpio.index.names) == ["league", "season", "team", "player"]
    assert sorted(limpio.index.get_level_values("player")) == ["Cubarsi", "Pedri"]


def test_tidy_descarta_las_cabeceras_repetidas() -> None:
    # FBref repite la cabecera cada 25 filas para poder leerla sin volver
    # arriba. Sin quitarlas entrarian como jugadores llamados "Player".
    limpio = tidy(extract_player_table(TABLA, "passing"), "ESP-La Liga", "2526")

    assert "Player" not in limpio.index.get_level_values("player")
    assert len(limpio) == 2


def test_tidy_conserva_la_cabecera_de_dos_niveles() -> None:
    # `transform.flatten_columns` la necesita para distinguir columnas que se
    # llaman igual en grupos distintos.
    limpio = tidy(extract_player_table(TABLA, "passing"), "ESP-La Liga", "2526")

    assert isinstance(limpio.columns, pd.MultiIndex)


def test_tidy_quita_las_columnas_de_navegacion() -> None:
    limpio = tidy(extract_player_table(TABLA, "passing"), "ESP-La Liga", "2526")

    aplanadas = {" ".join(str(p) for p in c) for c in limpio.columns}
    assert not any("Matches" in nombre for nombre in aplanadas)
