"""Tests de la normalizacion de posiciones."""

from __future__ import annotations

import pytest

from futbol_analytics.positions import is_hybrid, primary_position, split_positions


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("DF", ("DF",)),
        ("DF,MF", ("DF", "MF")),
        ("fw , mf", ("FW", "MF")),
        ("MF/FW", ("MF", "FW")),
        # FBref repite a veces el mismo grupo; no debe duplicarse.
        ("DF,DF", ("DF",)),
        (None, ()),
        ("", ()),
        ("Entrenador", ()),
    ],
)
def test_split_positions(raw: str | None, esperado: tuple[str, ...]) -> None:
    assert split_positions(raw) == esperado


def test_la_posicion_principal_es_la_primera_que_lista_fbref() -> None:
    # FBref ordena por minutos jugados, asi que la primera es la principal.
    assert primary_position("DF,MF") == "DF"
    assert primary_position("MF,DF") == "MF"


def test_sin_posicion_reconocible_devuelve_none() -> None:
    # Preferimos no asignar grupo a asignar uno equivocado: el grupo decide
    # contra quien se compara al jugador en los percentiles.
    assert primary_position("???") is None
    assert primary_position(None) is None


def test_los_hibridos_se_detectan() -> None:
    assert is_hybrid("DF,MF") is True
    assert is_hybrid("DF") is False
    assert is_hybrid(None) is False
