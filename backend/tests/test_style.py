"""Tests del clustering de estilo de equipo."""

from __future__ import annotations

import pandas as pd
import pytest

from futbol_analytics.analysis import style


def _equipos(n: int = 8) -> pd.DataFrame:
    """Equipos con un gradiente de presion y de territorio.

    Formato de `team_season`: una fila por equipo y perspectiva, con las
    metricas de Understat.
    """
    filas = []
    for i in range(n):
        # Del equipo que mas presiona (PPDA baja) al que menos.
        ppda = 6.0 + i * 1.5
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "for",
                "matches_played": 38.0,
                "goals": 60.0 - i * 3,
                "xg": 58.0 - i * 3,
                "np_xg": 55.0 - i * 3,
                "deep_completions": 400.0 - i * 25,
                "ppda": ppda,
            }
        )
        filas.append(
            {
                "league": "ESP-La Liga",
                "season": "2526",
                "team": f"Equipo {i}",
                "perspective": "against",
                "matches_played": 38.0,
                "goals": 30.0 + i * 2,
                "xg": 32.0 + i * 2,
                "np_xg": 30.0 + i * 2,
                "deep_completions": 200.0 + i * 20,
                "ppda": 12.0,
            }
        )
    return pd.DataFrame(filas)


def test_la_presion_usa_la_ppda_real_invertida() -> None:
    # PPDA baja es presion alta. Se invierte el signo para que, como el resto de
    # rasgos, "mas alto" signifique "mas de eso".
    features = style.build_features(_equipos())

    assert features["pressing"].iloc[0] == pytest.approx(-6.0)
    assert features["pressing"].iloc[0] > features["pressing"].iloc[-1]


def test_el_territorio_se_mide_por_partido() -> None:
    features = style.build_features(_equipos())

    assert features["territory"].iloc[0] == pytest.approx(400.0 / 38.0)


def test_lo_que_concede_va_con_el_signo_invertido() -> None:
    # Conceder poco es bueno, asi que el rasgo alto tiene que ser el del equipo
    # que menos concede.
    features = style.build_features(_equipos())

    assert features["chance_prevention"].iloc[0] > features["chance_prevention"].iloc[-1]


def test_la_finalizacion_compara_goles_con_xg() -> None:
    features = style.build_features(_equipos())

    assert features["finishing"].iloc[0] == pytest.approx((60.0 - 55.0) / 38.0)


def test_sin_la_perspectiva_del_rival_no_se_puede_medir_el_estilo() -> None:
    # Nada que dependa del rival (presion, posesion) es calculable sin ella.
    solo_a_favor = _equipos()[lambda frame: frame["perspective"] == "for"]

    with pytest.raises(ValueError, match="against"):
        style.build_features(solo_a_favor)


# --- Etiquetas --------------------------------------------------------------


def test_la_etiqueta_recoge_los_dos_rasgos_mas_extremos() -> None:
    centroide = pd.Series(
        {"pressing": 2.0, "territory": -1.5, "chance_creation": 0.1, "finishing": 0.2}
    )

    assert style.describe(centroide) == ("presión asfixiante, poca presencia en campo rival")


def test_el_rasgo_de_presion_ya_viene_invertido() -> None:
    # `build_features` invierte la PPDA, asi que aqui un valor alto siempre
    # significa presionar mas. El descriptor no tiene que volver a invertirlo.
    assert style.describe(pd.Series({"pressing": 2.0}), n_rasgos=1) == "presión asfixiante"
    assert style.describe(pd.Series({"pressing": -2.0}), n_rasgos=1) == "presión pasiva"


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
