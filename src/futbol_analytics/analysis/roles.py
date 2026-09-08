"""Clustering de roles de jugador.

Resuelve la limitacion que arrastra el esquema: FBref solo da `GK/DF/MF/FW`, y
comparar un central con un lateral no produce un percentil informativo. Aqui se
rellena `detailed_position`.

Dos decisiones de diseno gobiernan el modulo:

**1. Las features son composicionales, no volumenes.** En lugar de "entradas por
90", se usa "que porcentaje de sus toques son en el ultimo tercio" o "cuantos de
cada 100 pases son progresivos". El motivo es futbolistico: los volumenes llevan
dentro el estilo del equipo, de modo que dos laterales del mismo perfil caerian
en clusters distintos solo porque uno juega en un equipo que domina. Las
proporciones describen al jugador, no a su contexto.

**2. Los roles se fijan desde el futbol y el algoritmo los rellena.** No se
elige `k` por silhouette: se parte de una lista de roles reconocibles, se pide a
K-means ese numero de grupos y despues se empareja cada centroide con el rol al
que mas se parece. El silhouette se calcula, pero como control de calidad. Un
cluster que no sabes nombrar no sirve para contar nada, y contar algo es el
objetivo del proyecto.

Los porteros quedan fuera: sus metricas no tienen nada que ver con las del resto
y meterlos en el mismo espacio solo ensucia los grupos de campo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)

# Semilla fija: el mismo dato tiene que producir el mismo rol en cada ejecucion.
# Sin esto, un jugador cambiaria de rol entre dos recargas de la interfaz.
RANDOM_STATE = 20240101


@dataclass(frozen=True, slots=True)
class Feature:
    """Una proporcion: que parte de `denominator` representa `numerator`."""

    name: str
    numerator: str
    denominator: str
    label: str


# Perfil de un jugador expresado en proporciones. Todas son adimensionales, asi
# que el volumen de juego del equipo no entra en el calculo.
ROLE_FEATURES: tuple[Feature, ...] = (
    Feature("touch_share_def", "touches_def_third", "touches", "Toques en tercio defensivo"),
    Feature("touch_share_mid", "touches_mid_third", "touches", "Toques en tercio medio"),
    Feature("touch_share_att", "touches_att_third", "touches", "Toques en tercio ofensivo"),
    Feature("box_presence", "touches_att_pen", "touches", "Presencia en area rival"),
    Feature("progressive_pass_rate", "progressive_passes", "passes_attempted",
            "Pases progresivos por pase"),
    Feature("final_third_pass_rate", "passes_into_final_third", "passes_attempted",
            "Pases al ultimo tercio por pase"),
    Feature("cross_rate", "crosses_into_penalty_area", "passes_attempted",
            "Centros por pase"),
    Feature("key_pass_rate", "key_passes", "passes_attempted", "Pases clave por pase"),
    Feature("take_on_rate", "take_ons_attempted", "touches", "Regates por toque"),
    Feature("carry_progression", "carries_into_final_third", "carries",
            "Conducciones al ultimo tercio"),
    Feature("box_entries", "carries_into_penalty_area", "carries", "Conducciones al area"),
    Feature("shot_rate", "shots", "touches", "Tiros por toque"),
    Feature("aerial_rate", "aerials_won", "touches", "Duelos aereos por toque"),
    Feature("clearance_rate", "clearances", "touches", "Despejes por toque"),
    Feature("tackle_height", "tackles_att_third", "tackles", "Entradas en campo rival"),
    Feature("deep_defending", "tackles_def_third", "tackles", "Entradas en campo propio"),
)


@dataclass(frozen=True, slots=True)
class Archetype:
    """Un rol reconocible, descrito por como deberia verse en las features.

    `signature` asocia features a valores esperados en unidades de desviacion
    tipica: +1,5 significa "muy por encima de la media de su posicion". No hay
    que acertar el numero exacto; lo que importa es el patron relativo, porque
    el emparejamiento usa similitud de direccion.
    """

    name: str
    signature: dict[str, float]
    description: str


# Roles por grupo de posicion. Son los que un analista reconoceria y podria
# defender; el algoritmo solo decide quien cae en cada uno.
ARCHETYPES: dict[str, tuple[Archetype, ...]] = {
    "DF": (
        Archetype(
            "Central de area",
            {"aerial_rate": 1.5, "clearance_rate": 1.5, "deep_defending": 1.2,
             "touch_share_def": 1.2, "progressive_pass_rate": -0.5, "cross_rate": -0.8},
            "Defiende el area: duelo aereo, despeje y poca participacion con balon.",
        ),
        Archetype(
            "Central de progresion",
            {"progressive_pass_rate": 1.5, "final_third_pass_rate": 1.0,
             "touch_share_mid": 1.0, "carry_progression": 0.8, "aerial_rate": -0.3},
            "Central que saca el balon jugado y rompe la primera linea de presion.",
        ),
        Archetype(
            "Lateral profundo",
            {"cross_rate": 1.5, "touch_share_att": 1.3, "box_entries": 0.8,
             "take_on_rate": 0.7, "clearance_rate": -0.7},
            "Lateral que llega al fondo y centra: su aportacion es de banda.",
        ),
        Archetype(
            "Lateral de construccion",
            {"touch_share_mid": 1.2, "progressive_pass_rate": 1.0,
             "key_pass_rate": 0.5, "cross_rate": -0.6, "aerial_rate": -0.5},
            "Lateral que se mete dentro y participa en la salida, no en el centro.",
        ),
    ),
    "MF": (
        Archetype(
            "Pivote posicional",
            {"touch_share_def": 1.3, "deep_defending": 1.2, "clearance_rate": 0.6,
             "box_presence": -1.0, "shot_rate": -0.8},
            "Ancla delante de la defensa: recibe atras y casi nunca pisa el area.",
        ),
        Archetype(
            "Organizador",
            {"progressive_pass_rate": 1.5, "final_third_pass_rate": 1.4,
             "touch_share_mid": 1.0, "shot_rate": -0.4},
            "Centrocampista que dirige el juego: volumen alto de pase con progresion.",
        ),
        Archetype(
            "Interior de llegada",
            {"box_entries": 1.2, "carry_progression": 1.2, "touch_share_att": 1.0,
             "shot_rate": 0.8, "tackle_height": 0.6},
            "Llega desde segunda linea, conduce y pisa area.",
        ),
        Archetype(
            "Mediapunta",
            {"box_presence": 1.4, "key_pass_rate": 1.4, "shot_rate": 1.0,
             "touch_share_def": -1.2, "deep_defending": -0.8},
            "Juega entre lineas: ultimo pase y remate, poca tarea defensiva.",
        ),
    ),
    "FW": (
        Archetype(
            "Delantero de area",
            {"box_presence": 1.6, "shot_rate": 1.4, "aerial_rate": 1.0,
             "take_on_rate": -0.8, "touch_share_mid": -1.0},
            "Vive del remate: casi todos sus toques son en el area.",
        ),
        Archetype(
            "Delantero de enlace",
            {"touch_share_mid": 1.3, "key_pass_rate": 1.2, "final_third_pass_rate": 1.0,
             "box_presence": -0.6},
            "Baja a recibir y asocia; participa mas en la creacion que en el remate.",
        ),
        Archetype(
            "Extremo de banda",
            {"cross_rate": 1.5, "take_on_rate": 1.3, "touch_share_att": 1.0,
             "shot_rate": -0.5},
            "Ataca por fuera, encara y centra.",
        ),
        Archetype(
            "Extremo finalizador",
            {"shot_rate": 1.3, "box_presence": 1.2, "take_on_rate": 1.0,
             "cross_rate": -0.9},
            "Extremo que busca dentro para rematar en lugar de centrar.",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class RoleResult:
    """Resultado del clustering para un grupo de posicion."""

    assignments: pd.DataFrame
    centroids: pd.DataFrame
    silhouette: float | None
    position_group: str


def build_features(players: pd.DataFrame) -> pd.DataFrame:
    """Calcula el perfil composicional de cada jugador.

    Un denominador a cero (un central sin un solo regate registrado) da NaN, no
    cero: no sabemos su proporcion, no es que sea nula.
    """
    result = pd.DataFrame(index=players.index)
    for feature in ROLE_FEATURES:
        if feature.numerator not in players.columns or feature.denominator not in players.columns:
            logger.warning("Feature no calculable", extra={"feature": feature.name})
            continue
        numerador = pd.to_numeric(players[feature.numerator], errors="coerce")
        denominador = pd.to_numeric(players[feature.denominator], errors="coerce")
        result[feature.name] = numerador / denominador.where(denominador > 0)
    return result


def standardise(frame: pd.DataFrame) -> pd.DataFrame:
    """Lleva cada feature a desviaciones tipicas dentro de la poblacion.

    Los huecos se rellenan con cero, es decir, con la media: es la suposicion
    mas neutra posible para un jugador del que no tenemos ese dato.
    """
    media = frame.mean()
    desviacion = frame.std(ddof=0).replace(0.0, np.nan)
    return ((frame - media) / desviacion).fillna(0.0)


def assign_roles(players: pd.DataFrame, position_group: str) -> RoleResult:
    """Agrupa a los jugadores de una posicion y pone nombre a cada grupo.

    Args:
        players: Jugadores de un unico grupo de posicion, ya filtrados por
            minutos. El filtro importa: un jugador con 100 minutos tiene
            proporciones inestables y deformaria los centroides.
        position_group: `DF`, `MF` o `FW`. Los porteros no se agrupan.

    Raises:
        ValueError: Si el grupo no tiene roles definidos o hay menos jugadores
            que roles.
    """
    if position_group not in ARCHETYPES:
        raise ValueError(
            f"No hay roles definidos para {position_group!r}. Los porteros se analizan "
            "aparte, con sus propias metricas."
        )

    arquetipos = ARCHETYPES[position_group]
    k = len(arquetipos)
    if len(players) < k:
        raise ValueError(
            f"Hacen falta al menos {k} jugadores para {position_group}, hay {len(players)}."
        )

    features = standardise(build_features(players))
    modelo = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)
    etiquetas = modelo.fit_predict(features.to_numpy())

    centroides = pd.DataFrame(modelo.cluster_centers_, columns=features.columns)
    nombres = _match_archetypes(centroides, arquetipos)

    asignaciones = players.copy()
    asignaciones["cluster"] = etiquetas
    asignaciones["detailed_position"] = [nombres[etiqueta] for etiqueta in etiquetas]

    calidad = _silhouette(features.to_numpy(), etiquetas, k)
    logger.info(
        "Roles asignados",
        extra={
            "position_group": position_group,
            "jugadores": len(players),
            "silhouette": calidad,
            "reparto": pd.Series(asignaciones["detailed_position"]).value_counts().to_dict(),
        },
    )

    centroides.index = [nombres[i] for i in range(k)]
    return RoleResult(
        assignments=asignaciones,
        centroids=centroides,
        silhouette=calidad,
        position_group=position_group,
    )


def assign_all_roles(players: pd.DataFrame) -> pd.DataFrame:
    """Aplica el clustering a cada grupo de posicion por separado.

    Por separado y no en un unico espacio: mezclar centrales y delanteros haria
    que K-means gastase sus grupos en separar posiciones, que es justo lo que ya
    sabemos, en lugar de separar roles dentro de cada posicion.

    Ningun jugador se pierde: los porteros, los que no tienen posicion y los
    grupos demasiado pequenos para agrupar salen con `detailed_position` a nulo,
    igual que antes de esta fase.
    """
    if players.empty:
        return players.assign(detailed_position=None)

    piezas = []
    for position_group, subconjunto in players.groupby(
        players["position_group"], dropna=False, sort=False
    ):
        if position_group not in ARCHETYPES:
            piezas.append(subconjunto.assign(detailed_position=None))
            continue
        try:
            piezas.append(assign_roles(subconjunto, str(position_group)).assignments)
        except ValueError as error:
            logger.warning(
                "Grupo de posicion sin roles asignados",
                extra={"position_group": position_group, "motivo": str(error)},
            )
            piezas.append(subconjunto.assign(detailed_position=None))

    return pd.concat(piezas, ignore_index=True)


def _match_archetypes(
    centroids: pd.DataFrame,
    archetypes: tuple[Archetype, ...],
) -> dict[int, str]:
    """Empareja cada centroide con el rol al que mas se parece.

    Se usa asignacion optima (Hungaro) y no "el mas parecido para cada uno" por
    una razon practica: sin ella, dos clusters distintos podrian recibir el
    mismo nombre y otro rol quedarse vacio.
    """
    similitud = np.zeros((len(centroids), len(archetypes)))
    for j, arquetipo in enumerate(archetypes):
        firma = np.array([arquetipo.signature.get(col, 0.0) for col in centroids.columns])
        norma_firma = np.linalg.norm(firma)
        for i, centroide in enumerate(centroids.to_numpy()):
            norma_centro = np.linalg.norm(centroide)
            if norma_firma == 0 or norma_centro == 0:
                continue
            similitud[i, j] = float(centroide @ firma) / (norma_centro * norma_firma)

    filas, columnas = linear_sum_assignment(-similitud)
    return {
        int(fila): archetypes[int(columna)].name
        for fila, columna in zip(filas, columnas, strict=True)
    }


def _silhouette(matriz: np.ndarray, etiquetas: np.ndarray, k: int) -> float | None:
    """Calidad de la separacion, como control y no como criterio.

    Un valor bajo no invalida los roles: significa que los perfiles forman un
    continuo, que es como es el futbol de verdad. Pero si baja mucho conviene
    revisar si algun rol esta de mas.
    """
    if len(np.unique(etiquetas)) < 2 or len(matriz) <= k:
        return None
    return float(silhouette_score(matriz, etiquetas))
