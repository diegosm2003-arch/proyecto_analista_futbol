"""Tests de los hallazgos de portada.

Logica pura sobre DataFrames de ejemplo: no tocan la base de datos.
"""

from __future__ import annotations

import pandas as pd

from futbol_analytics.analysis import insights

APORTACION = ("np_xg", "assists", "key_passes", "xg_buildup")


def _jugadores() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # Marca muy por encima de sus ocasiones.
            {
                "league": "ESP-La Liga",
                "season": "2627",
                "team": "A",
                "player": "Racha",
                "np_goals": 8.0,
                "np_xg": 2.0,
                "age": 27,
            },
            # Marca lo que le corresponde.
            {
                "league": "ESP-La Liga",
                "season": "2627",
                "team": "B",
                "player": "Normal",
                "np_goals": 4.0,
                "np_xg": 4.1,
                "age": 19,
            },
            # Un gol con muy poco xG: no debe ganar por no tener muestra.
            {
                "league": "ESP-La Liga",
                "season": "2627",
                "team": "C",
                "player": "Chiripa",
                "np_goals": 1.0,
                "np_xg": 0.05,
                "age": 30,
            },
        ]
    )


def _percentiles(**por_jugador: dict[str, float]) -> pd.DataFrame:
    filas = []
    for jugador, metricas in por_jugador.items():
        for metrica, valor in metricas.items():
            filas.append(
                {
                    "league": "ESP-La Liga",
                    "season": "2627",
                    "team": "B",
                    "player": jugador,
                    "metric": metrica,
                    "label": metrica,
                    "percentile_per90": valor,
                }
            )
    return pd.DataFrame(filas)


def test_el_sobrerrendimiento_necesita_muestra() -> None:
    # "Chiripa" tiene la mayor proporcion goles/xG, pero con 0,05 de xG eso no
    # es un hallazgo: es un gol suelto.
    hallazgo = insights.overperformer(_jugadores())

    assert hallazgo is not None
    assert "Racha" in hallazgo.headline


def test_el_sobrerrendimiento_avisa_de_que_es_una_racha() -> None:
    # Sin el matiz, el hallazgo se lee como una virtud del jugador.
    hallazgo = insights.overperformer(_jugadores())

    assert "racha" in hallazgo.caveat.lower()


def test_una_promesa_no_se_destaca_por_las_tarjetas() -> None:
    # Fallo real: salia un canterano de 18 anos "destacado en el percentil 94 de
    # tarjetas amarillas". No es una promesa, es un chaval al que amonestan
    # mucho: las tarjetas describen como compite, no lo que aporta.
    percentiles = _percentiles(
        Normal={"yellow_cards": 99.0, "np_xg": 40.0},
    )

    hallazgo = insights.young_standout(_jugadores(), percentiles, metrics=APORTACION)

    assert hallazgo is None


def test_una_promesa_de_verdad_si_se_destaca() -> None:
    percentiles = _percentiles(
        Normal={"yellow_cards": 99.0, "assists": 95.0},
    )

    hallazgo = insights.young_standout(_jugadores(), percentiles, metrics=APORTACION)

    assert hallazgo is not None
    assert "Normal" in hallazgo.headline
    assert "assists" in hallazgo.headline or "asistencia" in hallazgo.headline.lower()


def test_sin_jugadores_no_se_inventa_un_hallazgo() -> None:
    # Media portada con huecos es peor que media portada con tres frases buenas.
    vacio = pd.DataFrame()

    assert insights.overperformer(vacio) is None
    assert insights.young_standout(vacio, vacio) is None
    assert insights.sharpest_contrast(vacio, {}) is None
    assert insights.territorial_team(vacio) is None


def test_el_contraste_encuentra_al_perfil_mas_desequilibrado() -> None:
    percentiles = _percentiles(
        Extremo={"np_xg": 98.0, "xg_buildup": 3.0},
        Regular={"np_xg": 50.0, "xg_buildup": 48.0},
    )
    familias = {"Finalizacion": ["np_xg"], "Construccion": ["xg_buildup"]}

    hallazgo = insights.sharpest_contrast(percentiles, familias)

    assert hallazgo is not None
    assert "Extremo" in hallazgo.headline
