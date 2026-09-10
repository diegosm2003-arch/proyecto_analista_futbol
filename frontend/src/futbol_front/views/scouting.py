"""Buscador de scouting: quién rinde bien y además encaja.

Va como ámbito propio y no dentro de la vista de jugadores porque busca en
dirección contraria. Allí se entra sabiendo el equipo y se baja hasta el
futbolista; aquí se entra sin saber a quién se busca y se sale con una lista.

Es la pregunta con la que trabaja de verdad una dirección deportiva, y la que
separa una herramienta de consulta de una de scouting: no *quién es bueno*, sino
*a quién puedo ir a buscar*. El percentil solo responde a la primera; la edad, el
contrato y el precio responden a la segunda.
"""

from __future__ import annotations

import streamlit as st

from futbol_front.client import ApiError
from futbol_front.presentation import season_label
from futbol_front.state import cached_catalog, cached_metrics, cached_scouting
from futbol_front.theme import apply

POSICIONES = {"Todas": None, "Defensas": "DF", "Centrocampistas": "MF", "Delanteros": "FW"}

# Ventanas de contrato con las que se habla en el mercado. Doce meses es el
# punto en el que un club se sienta a renovar o a vender; seis, cuando el
# jugador ya puede negociar con otros.
CONTRATO = {
    "Sin filtrar": None,
    "Menos de 6 meses": 6,
    "Menos de 12 meses": 12,
    "Menos de 24 meses": 24,
}


def render() -> None:
    # El buscador no se acota a una liga, asi que va con la paleta neutra.
    apply(None)

    try:
        catalogo = cached_catalog()
        metricas = cached_metrics()
    except ApiError as error:
        st.error(f"La API no responde: {error}")
        return

    if not catalogo["seasons"]:
        st.warning("No hay datos cargados todavía.")
        return

    st.subheader("Buscador de scouting")
    st.caption(
        "Quién rinde por encima de un percentil **y además** encaja por edad, contrato "
        "y precio. El percentil solo dice quién es bueno; lo demás dice a quién se puede "
        "ir a buscar."
    )

    filtros = _filtros(catalogo, metricas)
    try:
        resultado = cached_scouting(**filtros)
    except ApiError as error:
        st.error(str(error))
        return

    for aviso in resultado["caveats"]:
        st.caption(f":orange[{aviso}]")

    if not resultado["hits"]:
        st.info(
            "Ningún jugador cumple todos los criterios. Prueba a bajar el percentil o "
            "a ensanchar la ventana de contrato."
        )
        return

    st.dataframe(
        [
            {
                "Jugador": h["player"],
                "Equipo": h["team"],
                "Liga": h["league"],
                "Pos.": h["position_group"],
                "Edad": h["age"],
                "Contrato": h["contract_until"],
                "Meses": h["months_left"],
                "Valor": _millones(h["market_value_eur"]),
                "Minutos": h["minutes"],
                h["label"]: f"{h['percentile']:.0f}",
            }
            for h in resultado["hits"]
        ],
        hide_index=True,
        width="stretch",
    )


def _filtros(catalogo: dict, metricas: list[dict]) -> dict:
    """Los criterios de búsqueda, arriba como en el resto de la aplicación."""
    con_direccion = [m for m in metricas if m.get("higher_is_better") is True]
    etiquetas = {m["label"]: m["name"] for m in con_direccion}

    with st.container(border=True):
        temporada_c, metrica_c, posicion_c = st.columns([1, 2, 1])
        with temporada_c:
            temporada = st.selectbox(
                "Temporada",
                catalogo["seasons"],
                index=len(catalogo["seasons"]) - 1,
                format_func=season_label,
            )
        with metrica_c:
            # Solo métricas con dirección: buscar "los que más tarjetas ven" no
            # es scouting, y el catálogo marca cuáles miden aportación.
            metrica = st.selectbox("Destaca en", list(etiquetas))
        with posicion_c:
            posicion = st.selectbox("Posición", list(POSICIONES))

        percentil_c, edad_c, contrato_c, valor_c = st.columns(4)
        with percentil_c:
            percentil = st.slider("Percentil mínimo", 50, 99, 85)
        with edad_c:
            edad = st.slider("Edad máxima", 17, 40, 40)
        with contrato_c:
            contrato = st.selectbox("Contrato", list(CONTRATO))
        with valor_c:
            valor = st.slider("Valor máximo (M €)", 0, 200, 200, step=5)

    return {
        "season": temporada,
        "metric": etiquetas[metrica],
        "min_percentile": float(percentil),
        "position_group": POSICIONES[posicion],
        "max_age": edad if edad < 40 else None,
        "max_months_left": CONTRATO[contrato],
        "max_value_eur": float(valor) * 1e6 if valor < 200 else None,
    }


def _millones(valor: float | None) -> str:
    return "-" if valor is None else f"{valor / 1e6:,.1f} M".replace(",", ".")
