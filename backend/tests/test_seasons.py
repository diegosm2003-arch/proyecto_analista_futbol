"""Tests de los codigos de temporada."""

from __future__ import annotations

from datetime import date

import pytest

from futbol_analytics.seasons import current_season, season_code, season_label


@pytest.mark.parametrize(
    ("dia", "esperado"),
    [
        # Septiembre: la temporada 2026/27 ya ha empezado.
        (date(2026, 9, 8), "2627"),
        # Marzo: seguimos en la temporada que empezo el ano anterior.
        (date(2026, 3, 1), "2526"),
        # Julio cuenta ya como temporada nueva: hay pretemporada y fichajes, y
        # ninguna competicion de la anterior sigue viva.
        (date(2026, 7, 1), "2627"),
        (date(2026, 6, 30), "2526"),
        # Cambio de siglo, por si el formato de dos digitos se rompe.
        (date(1999, 9, 1), "9900"),
        (date(2000, 1, 15), "9900"),
    ],
)
def test_season_code(dia: date, esperado: str) -> None:
    assert season_code(dia) == esperado


def test_current_season_usa_la_fecha_de_hoy_por_defecto() -> None:
    codigo = current_season()

    assert len(codigo) == 4
    assert codigo.isdigit()


def test_current_season_acepta_una_fecha() -> None:
    assert current_season(date(2026, 9, 8)) == "2627"


def test_season_label_pone_la_barra_con_la_que_se_habla() -> None:
    assert season_label("2627") == "26/27"


def test_season_label_deja_igual_lo_que_no_tiene_forma_de_codigo() -> None:
    # El chat puede recibir cualquier cosa del modelo; season_label no debe
    # reventar ni inventar una barra donde no hay un codigo de temporada.
    assert season_label("raro") == "raro"
