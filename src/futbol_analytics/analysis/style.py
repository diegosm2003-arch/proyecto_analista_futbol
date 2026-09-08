"""Clustering de estilo de equipo.

Al reves que en los roles de jugador, aqui **el contexto es el objeto de
estudio**: se quiere saber cuanto balon tiene un equipo y donde defiende, no
depurarlo. Por eso las features son magnitudes con unidades y no proporciones
neutras.

Los grupos no se nombran de antemano, como si se hace con los roles: los estilos
cambian de temporada en temporada y fijar una lista seria forzar la realidad. En
su lugar, cada cluster se describe por sus rasgos mas extremos, lo que produce
etiquetas legibles ("dominio del balon, presion adelantada") sin inventar
categorias.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from futbol_analytics.analysis.roles import RANDOM_STATE, standardise

logger = logging.getLogger(__name__)

# Numero de estilos por defecto. Cinco separa razonablemente el panorama de una
# liga grande sin caer en grupos de un solo equipo.
DEFAULT_STYLES = 5

# Como se lee cada rasgo cuando esta muy por encima o muy por debajo de la media.
# Es el vocabulario con el que se construyen las etiquetas.
DESCRIPTORS: dict[str, tuple[str, str]] = {
    "possession": ("dominio del balon", "juego sin balon"),
    "passes_p90": ("mucho volumen de pase", "juego directo"),
    "progression_p90": ("progresion constante", "poca progresion"),
    "ppda": ("presion pasiva", "presion asfixiante"),
    "pressing_height": ("presion adelantada", "bloque bajo"),
    "final_third_presence": ("campo rival como territorio", "poca presencia en campo rival"),
    "shot_volume": ("mucho volumen de tiro", "poco volumen de tiro"),
    "chance_quality": ("ocasiones claras", "ocasiones de baja calidad"),
}


@dataclass(frozen=True, slots=True)
class StyleResult:
    """Resultado del clustering de estilos."""

    assignments: pd.DataFrame
    centroids: pd.DataFrame
    labels: dict[int, str]
    silhouette: float | None


def build_features(teams: pd.DataFrame) -> pd.DataFrame:
    """Construye los rasgos de estilo a partir de las dos perspectivas.

    Necesita `team_season` con las filas `for` y `against`: sin la del rival no
    se puede calcular nada que dependa de el, empezando por la presion.
    """
    claves = ["league", "season", "team"]
    a_favor = teams[teams["perspective"] == "for"].set_index(claves)
    en_contra = teams[teams["perspective"] == "against"].set_index(claves)
    if a_favor.empty or en_contra.empty:
        raise ValueError("Hacen falta las filas 'for' y 'against' de cada equipo.")

    noventas = pd.to_numeric(a_favor["minutes"], errors="coerce") / 90.0
    noventas = noventas.where(noventas > 0)

    features = pd.DataFrame(index=a_favor.index)
    features["passes_p90"] = a_favor["passes_attempted"] / noventas
    features["progression_p90"] = a_favor["progressive_passes"] / noventas
    features["final_third_presence"] = a_favor["touches_att_third"] / noventas
    features["shot_volume"] = a_favor["shots"] / noventas
    # Calidad de ocasion: npxG por tiro. Distingue al equipo que tira mucho de
    # lejos del que genera pocas ocasiones pero claras.
    tiros = pd.to_numeric(a_favor["shots"], errors="coerce")
    features["chance_quality"] = a_favor["npxg"] / tiros.where(tiros > 0)

    pases_propios = pd.to_numeric(a_favor["passes_attempted"], errors="coerce")
    pases_rival = pd.to_numeric(en_contra["passes_attempted"], errors="coerce")
    total = pases_propios.add(pases_rival)
    features["possession"] = (pases_propios / total.where(total > 0)) * 100.0

    # PPDA aproximada: pases que el rival completa por cada accion defensiva
    # propia. La PPDA canonica se limita al 60 % del campo del rival y FBref no
    # publica el pase rival por zonas, asi que esto ordena bien a los equipos
    # pero no es comparable con la PPDA de otras fuentes. Un valor BAJO es
    # presion alta, por eso el descriptor esta invertido.
    acciones = pd.to_numeric(a_favor["tackles"], errors="coerce").add(
        pd.to_numeric(a_favor["interceptions"], errors="coerce")
    )
    features["ppda"] = pases_rival / acciones.where(acciones > 0)

    entradas = pd.to_numeric(a_favor["tackles"], errors="coerce")
    features["pressing_height"] = a_favor["tackles_att_third"] / entradas.where(entradas > 0)

    return features


def cluster_styles(teams: pd.DataFrame, n_styles: int = DEFAULT_STYLES) -> StyleResult:
    """Agrupa equipos por estilo de juego.

    Raises:
        ValueError: Si hay menos equipos que estilos pedidos.
    """
    features = build_features(teams)
    if len(features) < n_styles:
        raise ValueError(f"Hacen falta al menos {n_styles} equipos, hay {len(features)}.")

    normalizadas = standardise(features)
    modelo = KMeans(n_clusters=n_styles, n_init=10, random_state=RANDOM_STATE)
    etiquetas = modelo.fit_predict(normalizadas.to_numpy())

    centroides = pd.DataFrame(modelo.cluster_centers_, columns=features.columns)
    nombres = {i: describe(centroides.iloc[i]) for i in range(n_styles)}

    asignaciones = features.reset_index()
    asignaciones["cluster"] = etiquetas
    asignaciones["style"] = [nombres[etiqueta] for etiqueta in etiquetas]

    calidad = None
    if len(np.unique(etiquetas)) >= 2 and len(normalizadas) > n_styles:
        calidad = float(silhouette_score(normalizadas.to_numpy(), etiquetas))

    logger.info(
        "Estilos de equipo asignados",
        extra={
            "equipos": len(features),
            "estilos": n_styles,
            "silhouette": calidad,
            "reparto": pd.Series(asignaciones["style"]).value_counts().to_dict(),
        },
    )
    return StyleResult(
        assignments=asignaciones,
        centroids=centroides,
        labels=nombres,
        silhouette=calidad,
    )


def describe(centroid: pd.Series, n_rasgos: int = 2) -> str:
    """Convierte un centroide en una etiqueta legible.

    Toma los rasgos mas alejados de la media y los traduce con el vocabulario de
    `DESCRIPTORS`. Preferimos esto a nombres inventados de antemano: la etiqueta
    sale del dato y sigue siendo defendible.
    """
    conocidos = centroid[[nombre for nombre in centroid.index if nombre in DESCRIPTORS]]
    if conocidos.empty:
        return "estilo sin describir"

    extremos = conocidos.reindex(conocidos.abs().sort_values(ascending=False).index)
    partes = []
    for nombre, valor in extremos.head(n_rasgos).items():
        alto, bajo = DESCRIPTORS[nombre]
        partes.append(alto if valor >= 0 else bajo)
    return ", ".join(partes)
