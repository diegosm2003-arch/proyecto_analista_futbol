"""Tests del planificador del ETL.

No levantan PostgreSQL ni esperan a que salte ningun disparo: se comprueba la
configuracion del planificador y que una carga fallida no se lleve por delante
el proceso.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from futbol_analytics.config import Settings, get_settings
from futbol_analytics.etl import scheduler
from futbol_analytics.etl.load import EtlAlreadyRunningError


@pytest.fixture(autouse=True)
def ajustes_limpios() -> None:
    """`get_settings` esta cacheado: hay que vaciarlo entre tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


MADRID = ZoneInfo("Europe/Madrid")
# Un martes cualquiera de la temporada 2026/27, a las 6 de la manana.
AHORA = datetime(2026, 9, 8, 6, 0, tzinfo=MADRID)

LUNES, MARTES, MIERCOLES, JUEVES = 0, 1, 2, 3


def _proximos_disparos(cuantos: int) -> list[datetime]:
    """Siguientes ejecuciones que programaria el planificador."""
    trabajo = scheduler.build_scheduler().get_job(scheduler.JOB_ID)
    disparos, anterior, ahora = [], None, AHORA
    for _ in range(cuantos):
        siguiente = trabajo.trigger.get_next_fire_time(anterior, ahora)
        disparos.append(siguiente)
        anterior, ahora = siguiente, siguiente
    return disparos


def test_la_cadencia_por_defecto_es_despues_de_jornada() -> None:
    ajustes = Settings(_env_file=None)

    assert ajustes.etl_schedule == "0 6 * * tue,thu"
    assert ajustes.schedule_timezone == "Europe/Madrid"
    assert ajustes.etl_run_on_start is False


def test_la_carga_cae_en_martes_y_jueves_de_verdad() -> None:
    # Trampa real: APScheduler numera 0 = lunes y el cron clasico 0 = domingo,
    # asi que "0 6 * * 2,4" cargaria miercoles y viernes. El viernes es ANTES de
    # la jornada, con lo que el ETL se ejecutaria sin datos nuevos y no se
    # ejecutaria cuando si los hay. Por eso la expresion usa nombres.
    dias = {disparo.weekday() for disparo in _proximos_disparos(4)}

    assert dias == {MARTES, JUEVES}
    assert MIERCOLES not in dias


def test_la_carga_es_por_la_manana_en_hora_local() -> None:
    # Madrid y no UTC: "el martes por la manana" tiene que significar lo mismo
    # en enero que en agosto, con el cambio de hora de por medio.
    disparo = _proximos_disparos(1)[0]

    assert (disparo.hour, disparo.minute) == (6, 0)
    assert disparo.tzinfo is not None


def test_el_planificador_respeta_la_cadencia_configurada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ETL_SCHEDULE", "30 7 * * mon")

    disparo = _proximos_disparos(1)[0]

    assert (disparo.weekday(), disparo.hour, disparo.minute) == (LUNES, 7, 30)


def test_solo_se_ejecuta_una_carga_a_la_vez() -> None:
    # Dos cargas simultaneas duplicarian la presion sobre FBref sin traer nada
    # nuevo. El candado sobre etl_run cubre el caso de dos contenedores; esto
    # cubre el de una carga que se alarga mas que el intervalo.
    trabajo = scheduler.build_scheduler().get_job(scheduler.JOB_ID)

    assert trabajo.max_instances == 1
    assert trabajo.coalesce is True


def test_un_fallo_de_carga_no_mata_al_planificador(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # FBref puede estar caido un martes y funcionar el jueves. Si el proceso
    # muriera, no volveria a intentarlo nunca.
    def revienta(*_a, **_k):
        raise RuntimeError("FBref no responde")

    monkeypatch.setattr(scheduler.pipeline, "run", revienta)

    scheduler.run_once()

    assert "fallado" in caplog.text.lower()


def test_una_carga_ya_en_marcha_no_es_un_fallo(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def ya_corriendo(*_a, **_k):
        raise EtlAlreadyRunningError("Ya hay una carga en marcha (id 7).")

    monkeypatch.setattr(scheduler.pipeline, "run", ya_corriendo)

    scheduler.run_once()

    assert "omitida" in caplog.text.lower()
    assert "fallado" not in caplog.text.lower()
