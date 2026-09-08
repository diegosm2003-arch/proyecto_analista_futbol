"""Tests de la configuracion. No requieren base de datos."""

from __future__ import annotations

import pytest

from futbol_analytics.config import BIG_5_LEAGUES, Settings


def test_valores_por_defecto_apuntan_a_las_big_5() -> None:
    settings = Settings(_env_file=None)

    assert settings.leagues == BIG_5_LEAGUES
    assert "ESP-La Liga" in settings.leagues
    # La poblacion de referencia debe ser mas amplia que la liga objetivo:
    # con una sola liga la muestra por posicion se queda corta.
    assert len(settings.leagues) == 5


def test_umbral_de_minutos_por_defecto_descarta_muestras_minimas() -> None:
    settings = Settings(_env_file=None)

    assert settings.min_minutes == 450


def test_listas_se_pueden_pasar_como_csv_desde_el_entorno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LEAGUES", "ESP-La Liga, ENG-Premier League ,")
    monkeypatch.setenv("SEASONS", "2324,2425")

    settings = Settings(_env_file=None)

    assert settings.leagues == ["ESP-La Liga", "ENG-Premier League"]
    assert settings.seasons == ["2324", "2425"]


def test_log_level_se_normaliza_a_mayusculas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert Settings(_env_file=None).log_level == "DEBUG"


def test_database_url_usa_psycopg_y_escapa_la_password() -> None:
    settings = Settings(
        _env_file=None,
        postgres_user="analista",
        postgres_password="p@ss w/ord",
        postgres_db="futbol",
        postgres_host="postgres",
        postgres_port=5432,
    )

    assert settings.database_url == (
        "postgresql+psycopg://analista:p%40ss+w%2Ford@postgres:5432/futbol"
    )
