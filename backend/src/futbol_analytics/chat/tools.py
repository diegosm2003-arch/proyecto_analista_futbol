"""Las herramientas que el chat puede usar.

**Nunca hay SQL libre.** El modelo no escribe consultas: elige entre un conjunto
cerrado de funciones con parámetros tipados, y cada una llama al mismo análisis
que usa la interfaz. Un modelo pequeño alucinando una consulta contra la base de
datos es un riesgo que no aporta nada a cambio.

**Cuatro herramientas, ni una más.** Es el límite práctico de un modelo de 3-4B:
por encima empieza a elegir mal, y una herramienta que se invoca cuando no toca
es peor que no tenerla. Por la misma razón las descripciones son de una línea —
un párrafo explicando cuándo usar cada una las confunde en lugar de aclararlas.

**Las herramientas devuelven texto corto, no tablas.** El modelo no ve el
DataFrame: ve tres o cuatro frases con los números ya interpretados. Volcarle
cuarenta filas gasta su contexto y le hace inventarse relaciones entre columnas
que nadie le ha pedido.

**Las advertencias viajan con el dato.** Si un percentil se calculó sobre cinco
jornadas, eso va dentro de la respuesta de la herramienta y no en el prompt del
sistema: en el prompt el modelo lo olvida a la tercera pregunta; pegado al
número, lo repite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pandas as pd

from futbol_analytics.api import services
from futbol_analytics.api.repository import DataAccess

logger = logging.getLogger(__name__)

# Percentil a partir del cual una metrica se menciona como algo destacable.
DESTACABLE = 85.0

# Cuantos jugadores devuelve una busqueda. Mas nombres no ayudan a un modelo
# pequeno: se limita a leerlos en voz alta y pierde el hilo de la pregunta.
MAX_RESULTADOS = 6

# Cortes de PPDA habituales en las cinco grandes: por debajo del primero se
# presiona muy arriba, por encima del segundo se espera atras.
PPDA_ALTA, PPDA_BAJA = 10.0, 14.0


def definitions() -> list[dict[str, Any]]:
    """El esquema de las herramientas, en el formato que espera Ollama."""
    return [
        {
            "type": "function",
            "function": {
                "name": "perfil_de_jugador",
                "description": "Percentiles y puntos fuertes de un jugador.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "jugador": {"type": "string", "description": "Nombre del jugador"},
                        "temporada": {"type": "string", "description": "Por ejemplo 2627"},
                    },
                    "required": ["jugador"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "comparar_jugadores",
                "description": "Compara dos jugadores y dice en qué se diferencian.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "jugador_a": {"type": "string"},
                        "jugador_b": {"type": "string"},
                        "temporada": {"type": "string"},
                    },
                    "required": ["jugador_a", "jugador_b"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "buscar_jugadores",
                "description": "Busca jugadores que destaquen en una métrica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metrica": {
                            "type": "string",
                            "description": "np_xg, xa, key_passes, xg_buildup, shots...",
                        },
                        "posicion": {"type": "string", "description": "DF, MF o FW"},
                        "temporada": {"type": "string"},
                    },
                    "required": ["metrica"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "estilo_de_equipo",
                "description": "Cómo juega un equipo: presión y territorio.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "equipo": {"type": "string"},
                        "temporada": {"type": "string"},
                    },
                    "required": ["equipo"],
                },
            },
        },
    ]


def dispatch(name: str, arguments: dict[str, Any], data: DataAccess, season: str) -> str:
    """Ejecuta una herramienta y devuelve su respuesta como texto.

    Una herramienta desconocida no revienta la conversación: se contesta que no
    existe y el modelo reformula. Un modelo pequeño se inventa nombres de
    función de vez en cuando, y tumbar el chat por eso sería peor.
    """
    handlers: dict[str, Callable[..., str]] = {
        "perfil_de_jugador": _perfil,
        "comparar_jugadores": _comparar,
        "buscar_jugadores": _buscar,
        "estilo_de_equipo": _estilo,
    }
    handler = handlers.get(name)
    if handler is None:
        logger.warning("Herramienta inexistente", extra={"herramienta": name})
        return f"No existe ninguna herramienta llamada {name!r}."

    temporada = _temporada_valida(arguments.get("temporada"), season, data)
    try:
        return handler(arguments, data, temporada)
    except Exception as error:  # noqa: BLE001
        # El fallo de una herramienta se cuenta, no se propaga: la conversacion
        # sigue y el modelo puede intentar otra cosa.
        logger.exception("Fallo al ejecutar una herramienta", extra={"herramienta": name})
        return f"No se ha podido responder a eso: {error}"


def _temporada_valida(pedida: object, por_defecto: str, data: DataAccess) -> str:
    """Acepta la temporada solo si esta cargada de verdad.

    Comprobar el formato no basta, y esto salio de verlo fallar. Un modelo
    pequeno arrastra palabras de la pregunta a los argumentos: ante "como va
    Pedri esta temporada" manda `temporada="esta"`, y ante una pregunta sin
    temporada se inventa una plausible como "2022", que tiene cuatro digitos y
    pasaba la comprobacion de formato. El resultado era una consulta vacia y una
    respuesta segura de si misma diciendo que no hay jugadores.

    Contra la lista de temporadas cargadas eso no puede pasar: lo que no esta,
    se sustituye por la actual.
    """
    texto = str(pedida or "").strip()
    if texto and texto in set(data.seasons()):
        return texto
    if texto:
        logger.info(
            "Temporada descartada por no estar cargada",
            extra={"recibida": texto, "usada": por_defecto},
        )
    return por_defecto


def _perfil(argumentos: dict, data: DataAccess, temporada: str) -> str:
    nombre = str(argumentos.get("jugador", "")).strip()
    percentiles = services.player_percentiles(data, temporada)
    suyo = _del_jugador(percentiles, nombre)
    if suyo.empty:
        return _no_encontrado(nombre, temporada, percentiles)

    ficha = suyo.iloc[0]
    fuertes = suyo[
        (suyo["percentile_per90"] >= DESTACABLE) & (suyo["higher_is_better"] == True)  # noqa: E712
    ].sort_values("percentile_per90", ascending=False)

    # La temporada se nombra en cada respuesta a proposito: sin ella el modelo
    # se inventa una plausible al redactar, y llego a hablar de "la temporada
    # 2022-2023" con datos de 2026/27 delante.
    partes = [
        f"En la temporada {temporada}: {ficha['player']} ({ficha['team']}, "
        f"{ficha['league']}), {ficha['position_group']}, "
        f"{int(ficha['minutes'])} minutos."
    ]
    if fuertes.empty:
        partes.append("No destaca por encima del percentil 85 en ninguna métrica.")
    else:
        destacadas = ", ".join(
            f"{f['label']} (percentil {f['percentile_per90']:.0f})"
            for _, f in fuertes.head(4).iterrows()
        )
        partes.append(f"Destaca en: {destacadas}.")

    partes.append(_aviso_de_muestra(data, temporada))
    return " ".join(p for p in partes if p)


def _comparar(argumentos: dict, data: DataAccess, temporada: str) -> str:
    a = str(argumentos.get("jugador_a", "")).strip()
    b = str(argumentos.get("jugador_b", "")).strip()
    percentiles = services.player_percentiles(data, temporada)

    suyo_a, suyo_b = _del_jugador(percentiles, a), _del_jugador(percentiles, b)
    if suyo_a.empty:
        return _no_encontrado(a, temporada, percentiles)
    if suyo_b.empty:
        return _no_encontrado(b, temporada, percentiles)

    grupo_a = suyo_a.iloc[0]["position_group"]
    grupo_b = suyo_b.iloc[0]["position_group"]
    if grupo_a != grupo_b:
        # Comparar un central con un delantero sobre los mismos ejes no dice
        # nada de ninguno de los dos, y el modelo no tiene por que saberlo.
        return (
            f"{a} juega de {grupo_a} y {b} de {grupo_b}. Sus percentiles están calculados "
            "contra poblaciones distintas, así que compararlos directamente no significa "
            "nada."
        )

    unidos = suyo_a.merge(suyo_b, on="metric", suffixes=("_a", "_b"))
    unidos["hueco"] = unidos["percentile_per90_a"] - unidos["percentile_per90_b"]
    mayores = unidos.reindex(unidos["hueco"].abs().sort_values(ascending=False).index)

    diferencias = []
    for _, fila in mayores.head(3).iterrows():
        mejor, peor = (a, b) if fila["hueco"] > 0 else (b, a)
        diferencias.append(
            f"{fila['label_a']}: {mejor} está {abs(fila['hueco']):.0f} percentiles por "
            f"encima de {peor}"
        )
    return f"En la temporada {temporada}, comparando {a} y {b}: " + ". ".join(diferencias) + "."


def _buscar(argumentos: dict, data: DataAccess, temporada: str) -> str:
    metrica = str(argumentos.get("metrica", "")).strip()
    posicion = argumentos.get("posicion")
    percentiles = services.player_percentiles(data, temporada)

    seleccion = percentiles[percentiles["metric"] == metrica]
    if seleccion.empty:
        disponibles = ", ".join(sorted(percentiles["metric"].unique())[:12])
        return f"No conozco la métrica {metrica!r}. Las que hay son: {disponibles}."

    if posicion:
        seleccion = seleccion[seleccion["position_group"] == str(posicion).upper()]
    if seleccion.empty:
        return f"Ningún jugador de esa posición tiene {metrica} en {temporada}."

    mejores = seleccion.sort_values("percentile_per90", ascending=False).head(MAX_RESULTADOS)
    etiqueta = mejores.iloc[0]["label"]
    lista = ", ".join(
        f"{f['player']} ({f['team']}, percentil {f['percentile_per90']:.0f})"
        for _, f in mejores.iterrows()
    )
    return (
        f"En la temporada {temporada}, los mejores en {etiqueta} son: {lista}. "
        f"{_aviso_de_muestra(data, temporada)}"
    )


def _estilo(argumentos: dict, data: DataAccess, temporada: str) -> str:
    nombre = str(argumentos.get("equipo", "")).strip()
    informe = services.team_styles(data, temporada, n_styles=6)
    asignaciones = informe.assignments

    suyo = asignaciones[asignaciones["team"].astype("string").str.lower() == nombre.lower()]
    if suyo.empty:
        parecidos = [e for e in asignaciones["team"].unique() if nombre.lower() in str(e).lower()]
        if not parecidos:
            return f"No tengo cargado a {nombre!r} en {temporada}."
        suyo = asignaciones[asignaciones["team"] == parecidos[0]]

    fila = suyo.iloc[0]
    ppda = -float(fila["pressing"]) if pd.notna(fila.get("pressing")) else None
    territorio = float(fila["territory"]) if pd.notna(fila.get("territory")) else None

    partes = [f"En la temporada {temporada}, {fila['team']} se agrupa como: {fila['style']}."]
    if ppda is not None:
        # La direccion la interpreta la herramienta, no el modelo. Dandole el
        # numero y la regla —"mas baja es mas presion"— contestaba que un PPDA
        # de 7,4 "indica una baja presion", que es justo lo contrario. Un modelo
        # de 3B no razona sobre la direccion de una metrica; repite lo que lee.
        partes.append(f"{_leer_ppda(ppda)} (PPDA de {ppda:.1f})")
    if territorio is not None:
        partes.append(f"y llega {territorio:.1f} veces por partido a zona de remate")
    return " ".join(partes) + "."


def _leer_ppda(ppda: float) -> str:
    """Traduce la PPDA a lo que significa, para no dejarselo al modelo."""
    if ppda < PPDA_ALTA:
        return "Presiona muy arriba"
    if ppda > PPDA_BAJA:
        return "Presiona poco y espera atras"
    return "Presiona a una altura media"


def _del_jugador(percentiles: pd.DataFrame, nombre: str) -> pd.DataFrame:
    """Filas de un jugador, tolerando que el nombre venga incompleto.

    El usuario escribe "Pedri" o "yamal", no el nombre exacto de la fuente, y el
    modelo se lo pasa a la herramienta tal cual.
    """
    if percentiles.empty or not nombre:
        return percentiles.iloc[:0]

    jugadores = percentiles["player"].astype("string")
    exacto = percentiles[jugadores.str.lower() == nombre.lower()]
    if not exacto.empty:
        return exacto
    return percentiles[jugadores.str.contains(nombre, case=False, na=False, regex=False)]


def _no_encontrado(nombre: str, temporada: str, percentiles: pd.DataFrame) -> str:
    """Dice que no está, sin inventarse a nadie parecido."""
    if percentiles.empty:
        return f"No hay datos cargados de la temporada {temporada}."
    return (
        f"No encuentro a {nombre!r} en {temporada}. Puede que no esté en las cinco "
        "grandes ligas o que no llegue al umbral de minutos para tener percentiles."
    )


def _aviso_de_muestra(data: DataAccess, temporada: str) -> str:
    """El aviso de temporada empezada, pegado al dato y no al prompt.

    En el prompt del sistema el modelo lo olvida a la tercera pregunta; dentro
    de la respuesta de la herramienta, lo repite.
    """
    contexto = services.population_context(data, temporada)
    if contexto["min_minutes"] >= contexto["configured_min_minutes"]:
        return ""
    return (
        f"Aviso: la temporada {temporada} está empezada y el umbral ha bajado a "
        f"{contexto['min_minutes']} minutos, así que estos percentiles son inestables."
    )
