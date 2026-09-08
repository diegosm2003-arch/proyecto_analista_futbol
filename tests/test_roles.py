"""Tests del clustering de roles.

Se generan jugadores sinteticos con perfiles deliberadamente separados y se
comprueba que el algoritmo los recupera y les pone nombres unicos. No se afirma
que cada grupo reciba un nombre concreto salvo cuando el perfil es inequivoco:
un test que exija eso seria fragil sin aportar mas garantia.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from futbol_analytics.analysis import roles

# Volumenes de referencia. Como las features son proporciones, el volumen no
# influye en el resultado: por eso se puede fijar igual para todos.
TOQUES, PASES, CONDUCCIONES, ENTRADAS = 1000.0, 800.0, 300.0, 50.0

# Perfiles de defensa, expresados como las proporciones que el modelo mira.
PERFILES_DF: dict[str, dict[str, float]] = {
    "area": {
        "def": 0.70, "mid": 0.25, "att": 0.05, "box": 0.005,
        "prog": 0.04, "final": 0.02, "cross": 0.001, "key": 0.002,
        "take_on": 0.005, "carry": 0.02, "entries": 0.002, "shot": 0.002,
        "aerial": 0.060, "clear": 0.050, "alto": 0.05, "bajo": 0.75,
    },
    "progresion": {
        "def": 0.55, "mid": 0.40, "att": 0.05, "box": 0.005,
        "prog": 0.14, "final": 0.10, "cross": 0.002, "key": 0.005,
        "take_on": 0.010, "carry": 0.10, "entries": 0.005, "shot": 0.004,
        "aerial": 0.020, "clear": 0.020, "alto": 0.10, "bajo": 0.65,
    },
    "lateral_profundo": {
        "def": 0.30, "mid": 0.35, "att": 0.35, "box": 0.020,
        "prog": 0.09, "final": 0.08, "cross": 0.030, "key": 0.020,
        "take_on": 0.040, "carry": 0.20, "entries": 0.030, "shot": 0.006,
        "aerial": 0.015, "clear": 0.012, "alto": 0.30, "bajo": 0.40,
    },
    "lateral_interior": {
        "def": 0.35, "mid": 0.50, "att": 0.15, "box": 0.008,
        "prog": 0.15, "final": 0.09, "cross": 0.004, "key": 0.015,
        "take_on": 0.020, "carry": 0.08, "entries": 0.008, "shot": 0.004,
        "aerial": 0.012, "clear": 0.010, "alto": 0.15, "bajo": 0.55,
    },
}


def _jugadores_sinteticos(por_perfil: int = 25, ruido: float = 0.03) -> pd.DataFrame:
    """Genera defensas con perfiles separados y algo de ruido."""
    generador = np.random.default_rng(7)
    filas = []
    for nombre, perfil in PERFILES_DF.items():
        for i in range(por_perfil):
            factor = 1.0 + generador.normal(0.0, ruido)
            filas.append(
                {
                    "league": "ESP-La Liga",
                    "season": "2526",
                    "team": f"Equipo {i}",
                    "player": f"{nombre}-{i}",
                    "perfil": nombre,
                    "position_group": "DF",
                    "minutes": 2000,
                    "touches": TOQUES,
                    "touches_def_third": TOQUES * perfil["def"] * factor,
                    "touches_mid_third": TOQUES * perfil["mid"] * factor,
                    "touches_att_third": TOQUES * perfil["att"] * factor,
                    "touches_att_pen": TOQUES * perfil["box"] * factor,
                    "passes_attempted": PASES,
                    "progressive_passes": PASES * perfil["prog"] * factor,
                    "passes_into_final_third": PASES * perfil["final"] * factor,
                    "crosses_into_penalty_area": PASES * perfil["cross"] * factor,
                    "key_passes": PASES * perfil["key"] * factor,
                    "take_ons_attempted": TOQUES * perfil["take_on"] * factor,
                    "carries": CONDUCCIONES,
                    "carries_into_final_third": CONDUCCIONES * perfil["carry"] * factor,
                    "carries_into_penalty_area": CONDUCCIONES * perfil["entries"] * factor,
                    "shots": TOQUES * perfil["shot"] * factor,
                    "aerials_won": TOQUES * perfil["aerial"] * factor,
                    "clearances": TOQUES * perfil["clear"] * factor,
                    "tackles": ENTRADAS,
                    "tackles_att_third": ENTRADAS * perfil["alto"] * factor,
                    "tackles_def_third": ENTRADAS * perfil["bajo"] * factor,
                }
            )
    return pd.DataFrame(filas)


# --- Features ---------------------------------------------------------------


def test_las_features_son_proporciones_y_no_volumenes() -> None:
    # Es lo que hace que el rol describa al jugador y no a su equipo: dos
    # laterales iguales en equipos con distinto volumen de juego dan lo mismo.
    poco = pd.DataFrame(
        {"touches": [500.0], "touches_att_third": [150.0], "carries": [100.0],
         "carries_into_final_third": [20.0], "passes_attempted": [400.0],
         "progressive_passes": [40.0]}
    )
    mucho = poco * 3

    assert roles.build_features(poco)["touch_share_att"].iloc[0] == pytest.approx(
        roles.build_features(mucho)["touch_share_att"].iloc[0]
    )


def test_los_tercios_reparten_el_total_de_toques() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=1, ruido=0.0)
    features = roles.build_features(jugadores)

    suma = features["touch_share_def"] + features["touch_share_mid"] + features["touch_share_att"]
    assert suma.round(6).eq(1.0).all()


def test_un_denominador_a_cero_da_hueco_y_no_cero() -> None:
    # Un central sin un solo regate registrado no tiene proporcion conocida.
    jugadores = pd.DataFrame({"touches": [0.0], "take_ons_attempted": [0.0]})

    assert pd.isna(roles.build_features(jugadores)["take_on_rate"].iloc[0])


def test_standardise_centra_y_escala() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})

    resultado = roles.standardise(frame)

    assert resultado["a"].mean() == pytest.approx(0.0)
    assert resultado["a"].std(ddof=0) == pytest.approx(1.0)


def test_standardise_no_divide_por_cero_en_una_feature_constante() -> None:
    frame = pd.DataFrame({"a": [2.0, 2.0, 2.0]})

    assert (roles.standardise(frame)["a"] == 0.0).all()


# --- Asignacion de roles ----------------------------------------------------


def test_cada_rol_recibe_un_nombre_distinto() -> None:
    # El emparejamiento hungaro existe justamente para esto: sin el, dos
    # clusters podrian llamarse igual y un rol quedarse sin nadie.
    resultado = roles.assign_roles(_jugadores_sinteticos(), "DF")

    asignados = set(resultado.assignments["detailed_position"])
    esperados = {arquetipo.name for arquetipo in roles.ARCHETYPES["DF"]}
    assert asignados == esperados


def test_cada_perfil_sintetico_cae_en_un_unico_rol() -> None:
    resultado = roles.assign_roles(_jugadores_sinteticos(), "DF")

    por_perfil = resultado.assignments.groupby("perfil")["detailed_position"].nunique()
    assert (por_perfil == 1).all()


def test_el_central_de_area_se_reconoce() -> None:
    # Es el perfil inequivoco: mucho duelo aereo y despeje, casi nada de pase
    # progresivo ni de centro.
    resultado = roles.assign_roles(_jugadores_sinteticos(), "DF")

    area = resultado.assignments[resultado.assignments["perfil"] == "area"]
    assert area["detailed_position"].iloc[0] == "Central de area"


def test_el_resultado_es_reproducible() -> None:
    # Sin semilla fija, un jugador cambiaria de rol entre dos recargas de la
    # interfaz, que es inaceptable en un producto de analisis.
    primero = roles.assign_roles(_jugadores_sinteticos(), "DF").assignments
    segundo = roles.assign_roles(_jugadores_sinteticos(), "DF").assignments

    assert primero["detailed_position"].tolist() == segundo["detailed_position"].tolist()


def test_se_calcula_el_silhouette_como_control() -> None:
    resultado = roles.assign_roles(_jugadores_sinteticos(), "DF")

    assert resultado.silhouette is not None
    # Con perfiles tan separados la particion tiene que ser buena.
    assert resultado.silhouette > 0.3


def test_los_porteros_no_se_agrupan() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=5)
    jugadores["position_group"] = "GK"

    with pytest.raises(ValueError, match="porteros"):
        roles.assign_roles(jugadores, "GK")


def test_no_se_agrupa_con_menos_jugadores_que_roles() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=1).head(3)

    with pytest.raises(ValueError, match="al menos"):
        roles.assign_roles(jugadores, "DF")


# --- Aplicacion a toda la poblacion -----------------------------------------


def test_assign_all_roles_no_pierde_a_nadie() -> None:
    defensas = _jugadores_sinteticos(por_perfil=10)
    porteros = defensas.head(3).copy()
    porteros["position_group"] = "GK"
    porteros["player"] = ["Portero 1", "Portero 2", "Portero 3"]
    todos = pd.concat([defensas, porteros], ignore_index=True)

    resultado = roles.assign_all_roles(todos)

    assert len(resultado) == len(todos)
    porteros_resultado = resultado[resultado["position_group"] == "GK"]
    assert porteros_resultado["detailed_position"].isna().all()


def test_assign_all_roles_deja_sin_rol_a_los_grupos_demasiado_pequenos() -> None:
    defensas = _jugadores_sinteticos(por_perfil=10)
    delanteros = defensas.head(2).copy()
    delanteros["position_group"] = "FW"
    delanteros["player"] = ["Punta 1", "Punta 2"]

    resultado = roles.assign_all_roles(pd.concat([defensas, delanteros], ignore_index=True))

    puntas = resultado[resultado["position_group"] == "FW"]
    assert len(puntas) == 2
    assert puntas["detailed_position"].isna().all()


def test_assign_all_roles_con_poblacion_vacia() -> None:
    vacio = pd.DataFrame(columns=["position_group"])

    resultado = roles.assign_all_roles(vacio)

    assert resultado.empty
    assert "detailed_position" in resultado.columns
