"""Tests de la preparacion de datos para los graficos."""

from __future__ import annotations

from typing import Any

from futbol_front import presentation
from futbol_front.presentation import (
    prepare_pizza,
    prepare_style_map,
    summarise_profile,
)

PLANTILLA = [
    {"metric": "npxg", "label": "xG sin penaltis", "category": "Ataque"},
    {"metric": "progressive_passes", "label": "Pases progresivos", "category": "Posesion"},
    {"metric": "tackles", "label": "Entradas", "category": "Defensa"},
]


def _perfil(**percentiles: float | None) -> dict[str, Any]:
    return {
        "metrics": [
            {
                "metric": nombre,
                "label": nombre,
                "percentile": valor,
                "higher_is_better": True,
            }
            for nombre, valor in percentiles.items()
        ]
    }


# --- Pizza chart ------------------------------------------------------------


def test_el_orden_lo_manda_la_plantilla_y_no_el_percentil() -> None:
    # La API devuelve las metricas ordenadas por percentil. Si el grafico las
    # pintase en ese orden, las porciones cambiarian de sitio en cada jugador y
    # dos graficos dejarian de ser comparables de un vistazo.
    perfil = _perfil(tackles=90.0, npxg=10.0, progressive_passes=50.0)

    datos = prepare_pizza(perfil, PLANTILLA)

    assert datos.labels == ["xG sin penaltis", "Pases progresivos", "Entradas"]
    assert datos.values == [10, 50, 90]


def test_las_categorias_acompanan_a_cada_porcion() -> None:
    datos = prepare_pizza(_perfil(npxg=50.0, progressive_passes=50.0, tackles=50.0), PLANTILLA)

    assert datos.categories == ["Ataque", "Posesion", "Defensa"]


def test_una_metrica_ausente_se_omite_y_se_reporta() -> None:
    # Preferimos un grafico con un eje menos y un aviso a rellenar el hueco con
    # un cero, que afirmaria algo falso sobre el jugador.
    datos = prepare_pizza(_perfil(npxg=40.0, tackles=60.0), PLANTILLA)

    assert datos.labels == ["xG sin penaltis", "Entradas"]
    assert datos.missing == ["progressive_passes"]


def test_un_percentil_nulo_cuenta_como_ausente() -> None:
    # Pasa con el ajuste por posesion cuando falta la posesion del equipo.
    datos = prepare_pizza(_perfil(npxg=40.0, progressive_passes=None, tackles=60.0), PLANTILLA)

    assert datos.missing == ["progressive_passes"]
    assert len(datos) == 2


def test_los_percentiles_se_redondean_a_entero() -> None:
    datos = prepare_pizza(_perfil(npxg=66.6, progressive_passes=33.2, tackles=50.5), PLANTILLA)

    assert datos.values == [67, 33, 50]
    assert all(isinstance(valor, int) for valor in datos.values)


def test_un_percentil_fuera_de_rango_se_recorta() -> None:
    datos = prepare_pizza(_perfil(npxg=140.0, progressive_passes=-5.0, tackles=50.0), PLANTILLA)

    assert datos.values == [100, 0, 50]


def test_un_perfil_vacio_da_un_grafico_vacio() -> None:
    datos = prepare_pizza({"metrics": []}, PLANTILLA)

    assert len(datos) == 0
    assert len(datos.missing) == 3


# --- Mapa de estilos --------------------------------------------------------


def _equipo(nombre: str, possession: float | None, ppda: float | None) -> dict[str, Any]:
    return {
        "team": nombre,
        "possession": possession,
        "ppda": ppda,
        "style": "dominio del balon",
        "cluster": 1,
    }


def test_el_mapa_recoge_a_los_equipos_completos() -> None:
    informe = {"teams": [_equipo("Girona", 55.0, 9.0), _equipo("Getafe", 42.0, 14.0)]}

    datos = prepare_style_map(informe)

    assert datos.teams == ["Girona", "Getafe"]
    assert datos.possession == [55.0, 42.0]
    assert datos.ppda == [9.0, 14.0]


def test_un_equipo_sin_ejes_se_descarta_en_lugar_de_ir_al_cero() -> None:
    # Pintarlo en el origen afirmaria que no presiona nada, que es una lectura
    # distinta de "no lo sabemos".
    informe = {"teams": [_equipo("Girona", 55.0, 9.0), _equipo("Sin datos", None, 12.0)]}

    datos = prepare_style_map(informe)

    assert datos.teams == ["Girona"]


def test_un_informe_vacio_no_revienta() -> None:
    assert len(prepare_style_map({"teams": []})) == 0


# --- Resumen ----------------------------------------------------------------


def test_el_resumen_toma_los_dos_percentiles_mas_altos() -> None:
    perfil = {
        "metrics": [
            {"label": "Pases progresivos", "percentile": 95.0, "higher_is_better": True},
            {"label": "Entradas", "percentile": 88.0, "higher_is_better": True},
            {"label": "Goles", "percentile": 20.0, "higher_is_better": True},
        ]
    }

    resumen = summarise_profile(perfil)

    assert "pases progresivos (percentil 95)" in resumen
    assert "entradas (percentil 88)" in resumen
    assert "goles" not in resumen


def test_el_resumen_ignora_las_metricas_de_estilo() -> None:
    # Estar en el percentil 99 de despejes no es un elogio: describe donde
    # defiende su equipo. En una frase de resumen se leeria como lo primero.
    perfil = {
        "metrics": [
            {"label": "Despejes", "percentile": 99.0, "higher_is_better": None},
            {"label": "Pases progresivos", "percentile": 70.0, "higher_is_better": True},
        ]
    }

    resumen = summarise_profile(perfil)

    assert "despejes" not in resumen
    assert "pases progresivos" in resumen


def test_el_resumen_ignora_las_metricas_donde_menos_es_mejor() -> None:
    perfil = {
        "metrics": [
            {"label": "Faltas cometidas", "percentile": 99.0, "higher_is_better": False},
            {"label": "Entradas", "percentile": 60.0, "higher_is_better": True},
        ]
    }

    assert "faltas" not in summarise_profile(perfil)


def test_sin_metricas_con_direccion_se_dice_claramente() -> None:
    perfil = {"metrics": [{"label": "Despejes", "percentile": 99.0, "higher_is_better": None}]}

    assert "Sin metricas suficientes" in summarise_profile(perfil)


# --- Nombre de fichero ------------------------------------------------------


def test_el_nombre_de_fichero_sobrevive_a_acentos_y_espacios() -> None:
    # Los nombres reales llevan acentos y puntos ("A. Garcia"), y eso da
    # problemas al guardar segun donde acabe el fichero.
    assert (
        presentation.chart_filename("Nico Williams", "2627", "per90")
        == "nico-williams-2627-per90.png"
    )
    assert presentation.chart_filename("Iñaki Peña") == "inaki-pena.png"
    assert presentation.chart_filename("A. García", "2627") == "a-garcia-2627.png"


def test_el_nombre_de_fichero_nunca_queda_vacio() -> None:
    assert presentation.chart_filename("...", "  ") == "grafico.png"


# --- Comparacion de dos jugadores -------------------------------------------


def test_la_comparacion_usa_los_mismos_ejes_y_el_mismo_orden() -> None:
    uno = _perfil(npxg=80.0, progressive_passes=60.0, tackles=40.0)
    otro = _perfil(tackles=90.0, npxg=20.0, progressive_passes=50.0)

    datos = presentation.prepare_comparison(uno, otro, PLANTILLA)

    assert datos.labels == ["xG sin penaltis", "Pases progresivos", "Entradas"]
    assert datos.values_a == [80, 60, 40]
    assert datos.values_b == [20, 50, 90]


def test_una_metrica_que_le_falta_a_uno_se_cae_de_la_comparacion() -> None:
    # Pintar la porcion del que si la tiene y dejar vacia la del otro se leeria
    # como que el segundo vale cero, que es falso y ademas es el error mas
    # danino en un grafico hecho para compararlos de un vistazo.
    uno = _perfil(npxg=80.0, progressive_passes=60.0, tackles=40.0)
    otro = _perfil(npxg=20.0, tackles=90.0)

    datos = presentation.prepare_comparison(uno, otro, PLANTILLA)

    assert datos.labels == ["xG sin penaltis", "Entradas"]
    assert "progressive_passes" in datos.missing
    assert len(datos.values_a) == len(datos.values_b) == 2


def test_sin_metricas_comunes_la_comparacion_queda_vacia() -> None:
    datos = presentation.prepare_comparison(_perfil(npxg=80.0), _perfil(tackles=50.0), PLANTILLA)

    assert len(datos) == 0
