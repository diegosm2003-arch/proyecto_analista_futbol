"""Tests del clustering de estilo de equipo."""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import style


def _equipos(n: int = 8) -> pd.DataFrame:
    """Equipos con un gradiente de posesion y de altura de presion."""
    filas = []
    for i in range(n):
        # Gradiente de posesion: del 25 % al 80 % sobre 1.200 pases por partido.
        dominio = 300.0 + i * 60.0  # pases propios
        rival = 1200.0 - dominio  # pases del rival
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "for",
                "minutes": 3420.0,
                "matches_played": 38.0,
                "passes_attempted": dominio,
                "passes_completed": dominio * 0.85,
                "progressive_passes": dominio * 0.10,
                "passes_into_final_third": dominio * 0.08,
                "touches_att_third": dominio * 0.5,
                "shots": 400.0 + i * 20.0,
                "npxg": 45.0 + i * 3.0,
                "goals": 45.0 + i * 3.0,
                "tackles": 700.0 - i * 40.0,
                "tackles_att_third": (700.0 - i * 40.0) * (0.1 + i * 0.03),
                "interceptions": 300.0 - i * 10.0,
            }
        )
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "against",
                "minutes": 3420.0,
                "matches_played": 38.0,
                "passes_attempted": rival,
                "passes_completed": rival * 0.85,
                "progressive_passes": rival * 0.10,
                "passes_into_final_third": rival * 0.08,
                "touches_att_third": rival * 0.5,
                "shots": 400.0,
                "npxg": 40.0,
                "goals": 40.0,
                "tackles": 600.0,
                "tackles_att_third": 60.0,
                "interceptions": 250.0,
            }
        )
    return pd.DataFrame(filas)


def test_la_posesion_sale_de_la_cuota_de_pases() -> None:
    features = style.build_features(_equipos())

    # Equipo 0: 300 pases propios de los 1.200 del partido.
    assert features["possession"].iloc[0] == pytest.approx(25.0)


def test_la_ppda_mide_pases_del_rival_por_accion_defensiva() -> None:
    features = style.build_features(_equipos())

    # Equipo 0: el rival da 900 pases; el equipo hace 700 entradas + 300
    # intercepciones = 1.000 acciones defensivas.
    assert features["ppda"].iloc[0] == pytest.approx(0.9)


def test_la_altura_de_presion_es_la_cuota_de_entradas_en_campo_rival() -> None:
    features = style.build_features(_equipos())

    assert features["pressing_height"].iloc[0] == pytest.approx(0.1)


def test_la_calidad_de_ocasion_es_npxg_por_tiro() -> None:
    features = style.build_features(_equipos())

    assert features["chance_quality"].iloc[0] == pytest.approx(45.0 / 400.0)


def test_sin_la_perspectiva_del_rival_no_se_puede_medir_el_estilo() -> None:
    # Nada que dependa del rival (presion, posesion) es calculable sin ella.
    solo_a_favor = _equipos()[lambda frame: frame["perspective"] == "for"]

    with pytest.raises(ValueError, match="against"):
        style.build_features(solo_a_favor)


# --- Etiquetas --------------------------------------------------------------


def test_la_etiqueta_recoge_los_dos_rasgos_mas_extremos() -> None:
    centroide = pd.Series(
        {"possession": 2.0, "ppda": -1.5, "shot_volume": 0.1, "chance_quality": 0.2}
    )

    assert style.describe(centroide) == "dominio del balon, presion asfixiante"


def test_una_ppda_baja_se_lee_como_presion_alta() -> None:
    # Detalle facil de invertir: PPDA baja significa que el rival da pocos pases
    # por cada accion defensiva, es decir, presion alta.
    assert style.describe(pd.Series({"ppda": -2.0}), n_rasgos=1) == "presion asfixiante"
    assert style.describe(pd.Series({"ppda": 2.0}), n_rasgos=1) == "presion pasiva"


def test_un_centroide_sin_rasgos_conocidos_no_revienta() -> None:
    assert style.describe(pd.Series({"inventado": 3.0})) == "estilo sin describir"


# --- Clustering -------------------------------------------------------------


def test_todos_los_equipos_reciben_un_estilo() -> None:
    resultado = style.cluster_styles(_equipos(12), n_styles=3)

    assert len(resultado.assignments) == 12
    assert resultado.assignments["style"].notna().all()
    assert len(resultado.labels) == 3


def test_los_extremos_del_gradiente_no_comparten_estilo() -> None:
    # El equipo que menos balon tiene y el que mas no pueden ser el mismo estilo.
    resultado = style.cluster_styles(_equipos(12), n_styles=3)
    asignaciones = resultado.assignments.set_index("team")["style"]

    assert asignaciones["Equipo 0"] != asignaciones["Equipo 11"]


def test_no_se_agrupa_con_menos_equipos_que_estilos() -> None:
    with pytest.raises(ValueError, match="al menos"):
        style.cluster_styles(_equipos(2), n_styles=5)
