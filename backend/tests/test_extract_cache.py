"""Tests de la politica de cache del scraping.

Es la decision que separa un ETL util de uno que parece funcionar: si la
temporada en curso se lee del cache, la carga programada terminaria con exito
cada martes devolviendo siempre los datos de la primera descarga.

No tocan la red: `soccerdata` se importa de forma perezosa dentro de `_fbref`,
asi que estas funciones se pueden probar sin tenerlo instalado.
"""

from __future__ import annotations

from datetime import date

import pytest

from futbol_analytics.etl.extract import _resolve_cache, needs_fresh_data

HOY = date(2026, 9, 8)  # temporada 2026/27 recien empezada


def test_la_temporada_en_curso_necesita_datos_frescos() -> None:
    assert needs_fresh_data(["2627"], today=HOY) is True


def test_una_temporada_cerrada_puede_leerse_del_cache() -> None:
    # Las estadisticas de una temporada terminada no cambian: volver a
    # descargarlas es castigar a FBref para nada.
    assert needs_fresh_data(["2526"], today=HOY) is False


def test_una_carga_mixta_se_trata_como_en_curso() -> None:
    # El control de cache de soccerdata es del lector entero, no por temporada:
    # si alguna es la actual, hay que descargar todo de nuevo.
    assert needs_fresh_data(["2425", "2526", "2627"], today=HOY) is True


def test_sin_temporadas_no_hace_falta_refrescar() -> None:
    assert needs_fresh_data([], today=HOY) is False


@pytest.mark.parametrize(
    ("temporadas", "use_cache", "no_cache_esperado"),
    [
        # Sin indicar nada, decide la temporada: es lo que quiere el proceso
        # programado.
        (["2627"], None, True),
        (["2526"], None, False),
        # Forzar el uso del cache sirve para depurar sin volver a descargar.
        (["2627"], True, False),
        # Y forzar la descarga, para cuando FBref corrige una temporada cerrada.
        (["2526"], False, True),
    ],
)
def test_resolve_cache(
    temporadas: list[str],
    use_cache: bool | None,
    no_cache_esperado: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("futbol_analytics.etl.extract.current_season", lambda *_a, **_k: "2627")

    assert _resolve_cache(temporadas, use_cache) is no_cache_esperado


# --- Pagina combinada de las Big 5 ------------------------------------------


def test_las_cinco_grandes_se_piden_como_pagina_combinada() -> None:
    # FBref limita a una peticion cada 7 segundos. La pagina combinada devuelve
    # los mismos datos (soccerdata reparte cada fila a su liga) con una quinta
    # parte de peticiones.
    from futbol_analytics.config import BIG_5_LEAGUES
    from futbol_analytics.etl.extract import BIG5_COMBINED, resolve_leagues

    assert resolve_leagues(list(BIG_5_LEAGUES)) == [BIG5_COMBINED]


def test_una_sola_liga_se_pide_tal_cual() -> None:
    from futbol_analytics.etl.extract import resolve_leagues

    assert resolve_leagues(["ESP-La Liga"]) == ["ESP-La Liga"]


def test_con_cuatro_de_las_cinco_no_se_sustituye() -> None:
    # No hay pagina combinada de cuatro ligas: sustituir traeria una de mas.
    from futbol_analytics.config import BIG_5_LEAGUES
    from futbol_analytics.etl.extract import resolve_leagues

    cuatro = list(BIG_5_LEAGUES)[:4]
    assert resolve_leagues(cuatro) == cuatro


def test_lo_que_no_sean_las_big_5_se_conserva() -> None:
    from futbol_analytics.config import BIG_5_LEAGUES
    from futbol_analytics.etl.extract import BIG5_COMBINED, resolve_leagues

    peticion = [*BIG_5_LEAGUES, "POR-Liga Portugal"]
    assert resolve_leagues(peticion) == [BIG5_COMBINED, "POR-Liga Portugal"]


def test_se_puede_desactivar(monkeypatch: pytest.MonkeyPatch) -> None:
    # Interruptor por si la pagina combinada se desincronizase de las
    # individuales, que es el unico riesgo de usarla.
    from futbol_analytics.config import BIG_5_LEAGUES, get_settings
    from futbol_analytics.etl.extract import resolve_leagues

    monkeypatch.setenv("USE_COMBINED_BIG5", "false")
    get_settings.cache_clear()
    try:
        assert resolve_leagues(list(BIG_5_LEAGUES)) == list(BIG_5_LEAGUES)
    finally:
        get_settings.cache_clear()
