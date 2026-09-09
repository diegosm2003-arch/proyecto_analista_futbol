"""Tests del parecido entre jugadores.

Logica pura sobre DataFrames de ejemplo: no tocan la base de datos.
"""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import similarity


def _fila(player: str, team: str, grupo: str, minutos: int, **percentiles: float) -> list[dict]:
    return [
        {
            "league": "ESP-La Liga",
            "season": "2627",
            "team": team,
            "player": player,
            "position_group": grupo,
            "minutes": minutos,
            "metric": metrica,
            "percentile_per90": valor,
        }
        for metrica, valor in percentiles.items()
    ]


EJES = ("np_xg", "shots", "xa", "key_passes", "xg_buildup")


def _poblacion() -> pd.DataFrame:
    filas = []
    filas += _fila(
        "Referencia", "A", "FW", 900, np_xg=90, shots=88, xa=30, key_passes=32, xg_buildup=25
    )
    # Casi calcado: mismo perfil y mismo nivel.
    filas += _fila(
        "Gemelo", "B", "FW", 900, np_xg=88, shots=86, xa=32, key_passes=30, xg_buildup=27
    )
    # Misma FORMA (rematador que no crea) pero muy por debajo de nivel.
    filas += _fila("Pobre", "C", "FW", 900, np_xg=30, shots=28, xa=8, key_passes=9, xg_buildup=6)
    # Perfil opuesto: crea y no remata.
    filas += _fila(
        "Creador", "D", "FW", 900, np_xg=20, shots=18, xa=95, key_passes=94, xg_buildup=90
    )
    # Identico al gemelo pero es defensa: no debe aparecer.
    filas += _fila(
        "Central", "E", "DF", 900, np_xg=88, shots=86, xa=32, key_passes=30, xg_buildup=27
    )
    # Identico pero con 80 minutos: muestra insuficiente.
    filas += _fila(
        "Suplente", "F", "FW", 80, np_xg=89, shots=87, xa=31, key_passes=31, xg_buildup=26
    )
    return pd.DataFrame(filas)


# Como lo llama la API: con el umbral de minutos de la temporada.
MINUTOS = 450


def test_el_mas_parecido_es_el_de_perfil_y_nivel_iguales() -> None:
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=3, min_minutes=MINUTOS).neighbours

    assert vecinos[0].player == "Gemelo"
    assert vecinos[0].similarity > 95


def test_el_nivel_cuenta_y_no_solo_la_forma_del_perfil() -> None:
    # "Pobre" tiene la MISMA forma que la referencia (remata mucho, crea poco)
    # pero treinta puntos por debajo en todo. Para un scout no es un jugador
    # parecido, y por eso la distancia es euclidea y no coseno: el coseno los
    # daria por identicos.
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=4, min_minutes=MINUTOS).neighbours
    posiciones = [v.player for v in vecinos]

    assert posiciones.index("Gemelo") < posiciones.index("Pobre")


def test_no_se_compara_con_otro_grupo_posicional() -> None:
    # "Central" tiene percentiles calcados, pero su percentil esta calculado
    # contra centrales: un 88 en tiros no significa lo mismo.
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=5, min_minutes=MINUTOS).neighbours

    assert "Central" not in [v.player for v in vecinos]


def test_un_jugador_sin_minutos_suficientes_queda_fuera() -> None:
    # Un perfil construido sobre 80 minutos no es un jugador parecido, es ruido.
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=5, min_minutes=450).neighbours

    assert "Suplente" not in [v.player for v in vecinos]


def test_se_dice_en_que_se_parecen_y_en_que_no() -> None:
    # Una lista de nombres no se puede defender ante nadie; con los ejes si.
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=1, min_minutes=MINUTOS).neighbours

    assert vecinos[0].closest
    assert vecinos[0].furthest
    assert set(vecinos[0].closest).isdisjoint(vecinos[0].furthest)


def test_el_perfil_opuesto_queda_el_ultimo() -> None:
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=4, min_minutes=MINUTOS).neighbours

    assert vecinos[-1].player == "Creador"


@pytest.mark.parametrize("nombre", ["Nadie", ""])
def test_un_jugador_que_no_esta_no_devuelve_nada(nombre: str) -> None:
    assert similarity.nearest(_poblacion(), nombre).neighbours == []


def test_con_muy_pocos_ejes_no_se_compara() -> None:
    # Con dos metricas, cualquiera se parece a cualquiera.
    filas = _fila("A", "X", "FW", 900, np_xg=90, shots=80) + _fila(
        "B", "Y", "FW", 900, np_xg=91, shots=81
    )

    assert similarity.nearest(pd.DataFrame(filas), "A").neighbours == []


def test_una_poblacion_vacia_no_revienta() -> None:
    assert similarity.nearest(pd.DataFrame(), "Referencia").neighbours == []


def test_sin_umbral_de_minutos_entra_cualquiera() -> None:
    # El filtro no es implicito: quien llama decide. La API le pasa el umbral
    # que ya aplica al resto de la plataforma.
    vecinos = similarity.nearest(_poblacion(), "Referencia", n=5, min_minutes=0).neighbours

    assert "Suplente" in [v.player for v in vecinos]


def test_las_metricas_que_no_separan_a_nadie_se_pueden_dejar_fuera() -> None:
    # Casi ningun futbolista ve una roja en una temporada, asi que ese eje da a
    # toda la poblacion por identica: infla el parecido de todos y ademas sale
    # como explicacion, tapando lo que de verdad los acerca.
    filas = _poblacion()
    rojas = [
        {**f, "metric": "red_cards", "percentile_per90": 50.0}
        for f in filas.to_dict("records")
        if f["metric"] == "np_xg"
    ]
    con_rojas = pd.concat([filas, pd.DataFrame(rojas)], ignore_index=True)

    vecinos = similarity.nearest(
        con_rojas, "Referencia", n=1, min_minutes=MINUTOS, metrics=EJES
    ).neighbours

    assert "red_cards" not in vecinos[0].closest
    assert "red_cards" not in vecinos[0].furthest
