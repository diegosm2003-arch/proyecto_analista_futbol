"""Clustering de perfiles ofensivos.

El diseno original agrupaba por rol posicional (central de area, lateral
profundo, pivote posicional...) a partir de los toques por zona del campo. Esas
metricas no existen en ninguna fuente accesible: FBref sirve vacias sus tablas
de posesion y defensa, y Understat no las publica.

Lo que si se puede hacer, y es defendible ante alguien que sabe de futbol, es
clasificar por **como participa el jugador en el ataque de su equipo**, usando la
relacion entre tres cifras que Understat si da:

- `np_xg`: lo que acaba en un remate suyo.
- `xa`: lo que acaba en un remate de otro tras su pase.
- `xg_buildup`: lo que participa sin rematar ni asistir.

Las tres reparten el mismo total (`xg_chain`), asi que sus proporciones dicen
que clase de futbolista es, no cuanto juega.

Dos decisiones se mantienen del diseno anterior:

**Las features son proporciones, no volumenes.** Los volumenes llevan dentro el
estilo del equipo: dos jugadores del mismo perfil caerian en grupos distintos
solo porque uno juega en un equipo que ataca mas.

**Los roles se fijan desde el futbol y el algoritmo los rellena.** No se elige
`k` por silhouette: se parte de cuatro perfiles reconocibles y se empareja cada
centroide con el que mas se parece. Un cluster que no sabes nombrar no sirve
para contar nada.

Cada grupo de posicion se agrupa por separado, asi que "constructor entre
defensas" y "constructor entre delanteros" son cosas distintas y ambas
informativas. Los porteros quedan fuera.
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
    # Que parte de su participacion acaba en un tiro suyo. Alto = finalizador.
    Feature("shot_share", "np_xg", "xg_chain", "Remate sobre participación"),
    # Que parte acaba en un tiro de otro tras su pase. Alto = creador.
    Feature("creation_share", "xa", "xg_chain", "Asistencia sobre participación"),
    # Que parte es participacion previa, sin rematar ni asistir. Alto =
    # constructor: el central que saca el balon o el pivote que hace de bisagra.
    Feature("buildup_share", "xg_buildup", "xg_chain", "Construcción sobre participación"),
    # Calidad del tiro que genera: xG por disparo. Separa al que remata desde el
    # area del que dispara de lejos.
    Feature("shot_quality", "np_xg", "shots", "xG por tiro"),
    # Calidad de la ocasion que crea: xA por pase clave.
    Feature("pass_quality", "xa", "key_passes", "xA por pase clave"),
    # Cuanto de su produccion es gol frente a lo esperado. No es una proporcion
    # de participacion sino de acierto, y por eso va aparte.
    Feature("finishing", "np_goals", "np_xg", "Goles sobre xG"),
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


# Doce perfiles ofensivos, los mismos para todas las posiciones de campo.
#
# Con las metricas de Understat no se pueden reconstruir los roles posicionales
# del diseno original (central de area, lateral profundo, pivote...): eso exigia
# toques por zona y entradas por tercio, que ninguna fuente accesible publica.
#
# Lo que si se puede es algo distinto y defendible: clasificar por COMO
# participa el jugador en el ataque de su equipo. Y como el clustering se hace
# dentro de cada grupo de posicion, "constructor entre defensas" y "constructor
# entre delanteros" son dos cosas muy distintas y ambas informativas.
#
# **La estructura no es libre.** Las tres cuotas —remate, creacion y
# construccion— son compositivas: reparten la misma participacion, asi que suman
# aproximadamente uno y no puede existir un perfil con las tres bajas. Los doce
# salen por tanto de cruzar QUE cuota domina con COMO la ejecuta, que es lo que
# miden las tres features libres: calidad de tiro, calidad de pase y acierto
# frente a lo esperado.
#
# **Doce nombres finos no arreglan la limitacion de fondo.** Todas las features
# son ofensivas, asi que a un central se le sigue clasificando por lo que hace
# con balon. Los nombres afinan; el agujero defensivo sigue ahi y la interfaz lo
# advierte.
ATTACKING_ARCHETYPES: tuple[Archetype, ...] = (
    # --- Domina el remate ---
    Archetype(
        "Finalizador de área",
        {"shot_share": 1.6, "shot_quality": 1.3, "buildup_share": -1.0, "creation_share": -0.6},
        "Casi toda su participación acaba en un remate suyo, y desde buena posición.",
    ),
    Archetype(
        "Tirador de volumen",
        {"shot_share": 1.3, "shot_quality": -1.4, "buildup_share": -0.7},
        "Remata mucho pero desde peores posiciones: dispara de lejos.",
    ),
    Archetype(
        "Rematador eficaz",
        {"shot_share": 1.1, "finishing": 1.5, "shot_quality": 0.3, "buildup_share": -0.6},
        "Marca por encima de lo que dicen sus ocasiones. Suele ser racha antes que virtud.",
    ),
    Archetype(
        "Rematador atascado",
        {"shot_share": 1.1, "finishing": -1.5, "buildup_share": -0.6},
        "Genera remates pero no los convierte. Tambien suele corregirse solo.",
    ),
    # --- Domina la creacion ---
    Archetype(
        "Generador de ocasiones claras",
        {"creation_share": 1.6, "pass_quality": 1.3, "shot_share": -0.8},
        "Su aportación es el último pase, y deja a compañeros en buena posición.",
    ),
    Archetype(
        "Volumen de pase clave",
        {"creation_share": 1.4, "pass_quality": -1.3, "shot_share": -0.6},
        "Da muchos pases de último tercio, pero la mayoría acaban en remates lejanos.",
    ),
    Archetype(
        "Extremo asociativo",
        {"creation_share": 1.0, "shot_share": 0.9, "buildup_share": -1.2},
        "Reparte su aportación entre rematar y asistir, casi nunca en la salida.",
    ),
    Archetype(
        "Creador retrasado",
        {"creation_share": 1.1, "buildup_share": 0.9, "shot_share": -1.4},
        "Asiste desde lejos del área y participa antes en la jugada. No remata.",
    ),
    # --- Domina la construccion ---
    Archetype(
        "Constructor puro",
        {"buildup_share": 1.7, "shot_share": -1.3, "creation_share": -1.0},
        "Participa en las jugadas que acaban en gol sin rematarlas ni asistirlas.",
    ),
    Archetype(
        "Bisagra",
        {"buildup_share": 1.2, "creation_share": 0.7, "shot_share": -1.2, "pass_quality": 0.4},
        "Enlaza la salida con el último tercio: construye y además da el pase previo.",
    ),
    Archetype(
        "Constructor con llegada",
        {"buildup_share": 1.2, "shot_share": 0.7, "creation_share": -1.0},
        "Sale con el balón y además aparece a rematar. Un perfil de llegada desde atrás.",
    ),
    Archetype(
        "Primer pase",
        {"buildup_share": 1.5, "pass_quality": -1.2, "shot_share": -1.0},
        "Inicia muchas jugadas, pero lejos del área: su pase rara vez genera ocasión.",
    ),
)

ARCHETYPES: dict[str, tuple[Archetype, ...]] = {
    "DF": ATTACKING_ARCHETYPES,
    "MF": ATTACKING_ARCHETYPES,
    "FW": ATTACKING_ARCHETYPES,
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
            "aparte, con sus propias métricas."
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
                "Grupo de posición sin roles asignados",
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
