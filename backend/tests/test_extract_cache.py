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
