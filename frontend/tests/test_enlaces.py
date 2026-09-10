"""Tests de la sincronización entre la URL y el estado.

No levantan la aplicación: se comprueba la lógica de qué viaja y qué no, que es
donde están las decisiones.
"""

from __future__ import annotations

from futbol_front import enlaces


def test_solo_viaja_lo_que_identifica_la_vista() -> None:
    # La temporada, la liga, el equipo y el ámbito definen qué se está mirando.
    # Que un desplegable esté abierto, no: meterlo todo haría la URL ilegible y
    # frágil, porque cualquier control nuevo cambiaría el formato del enlace.
    assert set(enlaces.COMPARTIDO) == {
        "destino",
        "liga_elegida",
        "equipo_elegido",
        "temporada_activa",
    }


def test_los_nombres_de_la_url_se_leen() -> None:
    # Un enlace tiene que decir de qué va antes de abrirlo, porque se comparte
    # en un mensaje donde nadie va a hacer clic a ciegas.
    assert enlaces.COMPARTIDO["liga_elegida"] == "liga"
    assert enlaces.COMPARTIDO["equipo_elegido"] == "equipo"
    assert enlaces.COMPARTIDO["temporada_activa"] == "temporada"


def test_la_url_solo_se_lee_una_vez(monkeypatch) -> None:
    # Sin esta guarda, cada reejecución del script volvería a aplicar los
    # parámetros originales y pisaría la navegación: al pulsar "volver a las
    # ligas" reaparecería la liga que traía el enlace.
    estado: dict[str, object] = {}
    monkeypatch.setattr(enlaces.st, "session_state", estado)
    monkeypatch.setattr(enlaces.st, "query_params", {"liga": "ESP-La Liga"})

    enlaces.leer_una_vez()
    assert estado["liga_elegida"] == "ESP-La Liga"

    # El usuario navega a otra parte.
    estado["liga_elegida"] = None
    enlaces.leer_una_vez()

    assert estado["liga_elegida"] is None


def test_un_valor_vacio_no_ensucia_el_enlace(monkeypatch) -> None:
    # Una URL con `?equipo=` no significa nada.
    escritos: dict[str, str] = {}

    class Parametros(dict):
        def clear(self) -> None:
            escritos.clear()

        def update(self, otros) -> None:  # type: ignore[override]
            escritos.update(otros)

    monkeypatch.setattr(
        enlaces.st, "session_state", {"liga_elegida": "ESP-La Liga", "equipo_elegido": None}
    )
    monkeypatch.setattr(enlaces.st, "query_params", Parametros())

    enlaces.escribir()

    assert escritos == {"liga": "ESP-La Liga"}
