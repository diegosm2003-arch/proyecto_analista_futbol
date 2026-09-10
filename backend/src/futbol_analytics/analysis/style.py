"""Clustering de estilo de equipo.

Al reves que en los perfiles de jugador, aqui **el contexto es el objeto de
estudio**: se quiere saber como presiona un equipo y cuanto territorio pisa, no
depurarlo.

Los rasgos salen de Understat, que publica **la PPDA real** por partido. Hasta
ahora se derivaba una aproximacion sobre todo el campo a partir de los pases del
rival, que ordenaba bien a los equipos pero no era comparable con la PPDA que
publica nadie mas. Esa salvedad desaparece.

Los grupos no se nombran de antemano: los estilos cambian de temporada en
temporada y fijar una lista seria forzar la realidad. Cada cluster se describe
por sus rasgos mas extremos, lo que produce etiquetas legibles sin inventar
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
    "pressing": ("presion asfixiante", "presion pasiva"),
    "territory": ("campo rival como territorio", "poca presencia en campo rival"),
    "chance_creation": ("genera mucho peligro", "genera poco peligro"),
    "chance_prevention": ("concede poco", "concede mucho"),
    "finishing": ("finaliza por encima de lo esperado", "desperdicia ocasiones"),
    "chance_quality": ("cada llegada es peligrosa", "llega mucho y remata mal"),
    "pressed": ("le presionan arriba", "le dejan salir jugando"),
    "box_defence": ("aguanta el asedio", "se le mete todo el mundo en el area"),
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
    se puede medir ni lo que concede ni cuanto le presionan.
    """
    claves = ["league", "season", "team"]
    a_favor = teams[teams["perspective"] == "for"].set_index(claves)
    en_contra = teams[teams["perspective"] == "against"].set_index(claves)
    if a_favor.empty or en_contra.empty:
        raise ValueError("Hacen falta las filas 'for' y 'against' de cada equipo.")

    partidos = pd.to_numeric(a_favor["matches_played"], errors="coerce")
    partidos = partidos.where(partidos > 0)

    features = pd.DataFrame(index=a_favor.index)

    # PPDA real de Understat. Se invierte el signo para que, como todos los
    # demas rasgos, "mas alto" signifique "mas de eso": un PPDA bajo es presion
    # alta, y dejarlo sin invertir haria que la etiqueta dijese lo contrario de
    # lo que pasa.
    features["pressing"] = -pd.to_numeric(a_favor["ppda"], errors="coerce")

    # Llegadas a zona de remate por partido: cuanto territorio pisa de verdad,
    # que no es lo mismo que cuanto balon tiene.
    features["territory"] = a_favor["deep_completions"] / partidos
    features["chance_creation"] = a_favor["np_xg"] / partidos
    # Lo que concede, con el signo invertido por la misma razon que la presion.
    features["chance_prevention"] = -(en_contra["np_xg"] / partidos)

    # Goles menos xG: si finaliza por encima o por debajo de lo esperado. Es
    # rendimiento, no estilo, pero separa equipos que se parecen en todo lo
    # demas y explica clasificaciones que el xG solo no explica.
    goles = pd.to_numeric(a_favor["goals"], errors="coerce")
    xg = pd.to_numeric(a_favor["np_xg"], errors="coerce")
    features["finishing"] = (goles - xg) / partidos

    # Peligro por llegada, no por partido. Separa dos equipos que la media por
    # partido confunde: el que pisa mucho el area y remata desde cualquier sitio
    # y el que llega menos pero cada llegada acaba en ocasion. Son estilos
    # distintos y hasta ahora salian en el mismo grupo.
    llegadas = pd.to_numeric(a_favor["deep_completions"], errors="coerce")
    features["chance_quality"] = xg / llegadas.where(llegadas > 0)

    # Cuanto le presionan a el. Es un rasgo de estilo por derecho propio: hay
    # equipos a los que todo el mundo va a buscar arriba y otros a los que se les
    # deja salir y se les espera. Se invierte igual que la presion propia, para
    # que "mas alto" siga significando "mas de eso".
    features["pressed"] = -pd.to_numeric(en_contra["ppda"], errors="coerce")

    # Llegadas del rival a su zona de remate, por partido. No es lo mismo que el
    # peligro que concede: un bloque bajo puede permitir muchas entradas al area
    # y defenderlas bien, y hasta ahora los dos casos caian en el mismo grupo.
    concedidas = pd.to_numeric(en_contra["deep_completions"], errors="coerce")
    features["box_defence"] = -(concedidas / partidos)

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
