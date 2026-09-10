"""Tests del clustering de perfiles ofensivos.

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

# xGChain de referencia: el total que reparten las tres formas de participar.
CADENA = 6.0

# Perfiles expresados como el reparto de esa participacion. Las tres cuotas
# suman uno: es lo que hace que describan al jugador y no cuanto juega.
# Perfiles expresados como el reparto de esa participacion. Las tres cuotas
# suman uno: es lo que hace que describan al jugador y no cuanto juega.
#
# Hay uno por arquetipo. Antes eran cuatro y los arquetipos pasaron a doce: con
# menos perfiles que grupos, el clustering parte perfiles identicos en trozos
# arbitrarios y los tests dejan de comprobar nada.
PERFILES: dict[str, dict[str, float]] = {
    # --- Domina el remate ---
    "finalizador_area": {
        "remate": 0.70,
        "asistencia": 0.10,
        "construccion": 0.20,
        "tiros": 32.0,
        "pases_clave": 12.0,
        "acierto": 1.00,
    },
    # Mismo volumen de remate, peor calidad por tiro: dispara de lejos.
    "tirador_volumen": {
        "remate": 0.65,
        "asistencia": 0.10,
        "construccion": 0.25,
        "tiros": 135.0,
        "pases_clave": 14.0,
        "acierto": 1.00,
    },
    # Estos dos solo se diferencian en el acierto, que es justo lo que se quiere
    # comprobar: que el modelo separa marcar de generar.
    "rematador_eficaz": {
        "remate": 0.58,
        "asistencia": 0.12,
        "construccion": 0.30,
        "tiros": 60.0,
        "pases_clave": 14.0,
        "acierto": 1.55,
    },
    "rematador_atascado": {
        "remate": 0.58,
        "asistencia": 0.12,
        "construccion": 0.30,
        "tiros": 60.0,
        "pases_clave": 14.0,
        "acierto": 0.50,
    },
    # --- Domina la creacion ---
    "generador_claras": {
        "remate": 0.12,
        "asistencia": 0.58,
        "construccion": 0.30,
        "tiros": 20.0,
        "pases_clave": 38.0,
        "acierto": 1.00,
    },
    "volumen_pase": {
        "remate": 0.12,
        "asistencia": 0.55,
        "construccion": 0.33,
        "tiros": 20.0,
        "pases_clave": 150.0,
        "acierto": 1.00,
    },
    "extremo_asociativo": {
        "remate": 0.42,
        "asistencia": 0.40,
        "construccion": 0.18,
        "tiros": 62.0,
        "pases_clave": 52.0,
        "acierto": 1.00,
    },
    "creador_retrasado": {
        "remate": 0.08,
        "asistencia": 0.42,
        "construccion": 0.50,
        "tiros": 11.0,
        "pases_clave": 46.0,
        "acierto": 1.00,
    },
    # --- Domina la construccion ---
    "constructor_puro": {
        "remate": 0.05,
        "asistencia": 0.08,
        "construccion": 0.87,
        "tiros": 8.0,
        "pases_clave": 9.0,
        "acierto": 1.00,
    },
    "bisagra": {
        "remate": 0.08,
        "asistencia": 0.27,
        "construccion": 0.65,
        "tiros": 11.0,
        "pases_clave": 26.0,
        "acierto": 1.00,
    },
    "constructor_llegada": {
        "remate": 0.31,
        "asistencia": 0.09,
        "construccion": 0.60,
        "tiros": 33.0,
        "pases_clave": 11.0,
        "acierto": 1.00,
    },
    "primer_pase": {
        "remate": 0.07,
        "asistencia": 0.13,
        "construccion": 0.80,
        "tiros": 10.0,
        "pases_clave": 95.0,
        "acierto": 1.00,
    },
}


def _jugadores_sinteticos(por_perfil: int = 25, ruido: float = 0.03) -> pd.DataFrame:
    """Genera jugadores de campo con perfiles separados y algo de ruido."""
    generador = np.random.default_rng(7)
    filas = []
    for nombre, perfil in PERFILES.items():
        for i in range(por_perfil):
            factor = 1.0 + generador.normal(0.0, ruido)
            np_xg = CADENA * perfil["remate"] * factor
            filas.append(
                {
                    "league": "ESP-La Liga",
                    "season": "2526",
                    "team": f"Equipo {i}",
                    "player": f"{nombre}-{i}",
                    "perfil": nombre,
                    "position_group": "MF",
                    "minutes": 2000,
                    "xg_chain": CADENA,
                    "np_xg": np_xg,
                    "xa": CADENA * perfil["asistencia"] * factor,
                    "xg_buildup": CADENA * perfil["construccion"] * factor,
                    "shots": perfil["tiros"] * factor,
                    "key_passes": perfil["pases_clave"] * factor,
                    "np_goals": np_xg * perfil["acierto"],
                }
            )
    return pd.DataFrame(filas)


# --- Features ---------------------------------------------------------------


def test_las_features_son_proporciones_y_no_volumenes() -> None:
    # Es lo que hace que el perfil describa al jugador y no a su equipo: dos
    # jugadores iguales en equipos que atacan mas o menos dan lo mismo.
    poco = pd.DataFrame({"np_xg": [2.0], "xg_chain": [8.0], "shots": [20.0]})
    mucho = poco * 3

    assert roles.build_features(poco)["shot_share"].iloc[0] == pytest.approx(
        roles.build_features(mucho)["shot_share"].iloc[0]
    )


def test_las_tres_cuotas_reparten_la_participacion() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=1, ruido=0.0)
    features = roles.build_features(jugadores)

    suma = features["shot_share"] + features["creation_share"] + features["buildup_share"]
    assert suma.round(6).eq(1.0).all()


def test_un_denominador_a_cero_da_hueco_y_no_cero() -> None:
    # Un jugador que no ha participado en ninguna jugada de gol no tiene
    # proporcion conocida: no es que valga cero.
    jugadores = pd.DataFrame({"np_xg": [0.0], "xg_chain": [0.0]})

    assert pd.isna(roles.build_features(jugadores)["shot_share"].iloc[0])


def test_standardise_centra_y_escala() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})

    resultado = roles.standardise(frame)

    assert resultado["a"].mean() == pytest.approx(0.0)
    assert resultado["a"].std(ddof=0) == pytest.approx(1.0)


def test_standardise_no_divide_por_cero_en_una_feature_constante() -> None:
    frame = pd.DataFrame({"a": [2.0, 2.0, 2.0]})

    assert (roles.standardise(frame)["a"] == 0.0).all()


# --- Asignacion de perfiles -------------------------------------------------


def test_cada_perfil_recibe_un_nombre_distinto() -> None:
    # El emparejamiento hungaro existe justamente para esto: sin el, dos
    # clusters podrian llamarse igual y un perfil quedarse sin nadie.
    resultado = roles.assign_roles(_jugadores_sinteticos(), "MF")

    asignados = set(resultado.assignments["detailed_position"])
    esperados = {arquetipo.name for arquetipo in roles.ARCHETYPES["MF"]}
    assert asignados == esperados


def test_cada_perfil_sintetico_cae_en_un_unico_grupo() -> None:
    resultado = roles.assign_roles(_jugadores_sinteticos(), "MF")

    por_perfil = resultado.assignments.groupby("perfil")["detailed_position"].nunique()
    assert (por_perfil == 1).all()


def test_el_constructor_se_reconoce() -> None:
    # Es el perfil inequivoco: casi toda su participacion es previa al remate, y
    # ademas da pocos pases clave, que es lo que lo separa del "Primer pase".
    resultado = roles.assign_roles(_jugadores_sinteticos(), "MF")

    constructores = resultado.assignments[resultado.assignments["perfil"] == "constructor_puro"]
    assert constructores["detailed_position"].iloc[0] == "Constructor puro"


def test_el_resultado_es_reproducible() -> None:
    # Sin semilla fija, un jugador cambiaria de perfil entre dos recargas de la
    # interfaz, que es inaceptable en un producto de analisis.
    primero = roles.assign_roles(_jugadores_sinteticos(), "MF").assignments
    segundo = roles.assign_roles(_jugadores_sinteticos(), "MF").assignments

    assert primero["detailed_position"].tolist() == segundo["detailed_position"].tolist()


def test_se_calcula_el_silhouette_como_control() -> None:
    resultado = roles.assign_roles(_jugadores_sinteticos(), "MF")

    assert resultado.silhouette is not None
    assert resultado.silhouette > 0.3


def test_los_porteros_no_se_agrupan() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=5)
    jugadores["position_group"] = "GK"

    with pytest.raises(ValueError, match="porteros"):
        roles.assign_roles(jugadores, "GK")


def test_no_se_agrupa_con_menos_jugadores_que_perfiles() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=1).head(3)

    with pytest.raises(ValueError, match="al menos"):
        roles.assign_roles(jugadores, "MF")


# --- Aplicacion a toda la poblacion -----------------------------------------


def test_assign_all_roles_no_pierde_a_nadie() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=10)
    porteros = jugadores.head(3).copy()
    porteros["position_group"] = "GK"
    porteros["player"] = ["Portero 1", "Portero 2", "Portero 3"]
    todos = pd.concat([jugadores, porteros], ignore_index=True)

    resultado = roles.assign_all_roles(todos)

    assert len(resultado) == len(todos)
    assert resultado[resultado["position_group"] == "GK"]["detailed_position"].isna().all()


def test_assign_all_roles_deja_sin_perfil_a_los_grupos_pequenos() -> None:
    jugadores = _jugadores_sinteticos(por_perfil=10)
    delanteros = jugadores.head(2).copy()
    delanteros["position_group"] = "FW"
    delanteros["player"] = ["Punta 1", "Punta 2"]

    resultado = roles.assign_all_roles(pd.concat([jugadores, delanteros], ignore_index=True))

    puntas = resultado[resultado["position_group"] == "FW"]
    assert len(puntas) == 2
    assert puntas["detailed_position"].isna().all()


def test_assign_all_roles_con_poblacion_vacia() -> None:
    vacio = pd.DataFrame(columns=["position_group"])

    resultado = roles.assign_all_roles(vacio)

    assert resultado.empty
    assert "detailed_position" in resultado.columns
