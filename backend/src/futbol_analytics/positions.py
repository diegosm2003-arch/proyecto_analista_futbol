"""Normalizacion de posiciones.

FBref, en las estadisticas de temporada, solo publica la posicion como
`GK` / `DF` / `MF` / `FW` y combinaciones (`DF,MF`, `FW,MF`). No distingue un
central de un lateral, ni un mediocentro posicional de un mediapunta.

Esto es una limitacion real del dato, no un detalle de implementacion: comparar
a un central con un lateral en centros al area o en duelos aereos no produce un
percentil informativo. Por eso el esquema guarda dos cosas distintas:

- `position_group`: el grupo grueso que FBref si da. Es honesto y verificable.
- `detailed_position`: nulo en esta fase. Lo rellenara el clustering de roles de
  la fase 3, a partir de las metricas que el ETL ya guarda (toques por zona del
  campo, centros, duelos aereos, conducciones progresivas), que separan esos
  perfiles sin necesidad de inventar una heuristica a ojo.

Mientras `detailed_position` sea nulo, cualquier percentil calculado dentro del
grupo `DF` mezcla centrales y laterales y debe leerse con esa reserva.
"""

from __future__ import annotations

# Orden de prioridad para elegir la posicion principal cuando FBref publica
# varias. FBref lista primero la mas frecuente, asi que en la practica basta con
# quedarse con la primera; este orden solo resuelve valores mal formados.
POSITION_GROUPS: tuple[str, ...] = ("GK", "DF", "MF", "FW")

# Understat describe la posicion con letras sueltas separadas por espacios:
# "D S" es un defensa que ademas entro desde el banquillo, "F M S" un jugador
# usado de delantero y de medio. La "S" es un marcador de suplencia, no una
# posicion, y se descarta.
SUBSTITUTE_MARKER = "S"

_ALIASES: dict[str, str] = {
    "GK": "GK",
    "DF": "DF",
    "MF": "MF",
    "FW": "FW",
    # Alias que aparecen en algunas paginas y temporadas de FBref.
    "D": "DF",
    "M": "MF",
    "F": "FW",
    "G": "GK",
    "DEF": "DF",
    "MID": "MF",
    "FWD": "FW",
}


def split_positions(raw: str | None) -> tuple[str, ...]:
    """Descompone el campo `pos` de FBref en grupos de posicion normalizados.

    >>> split_positions("DF,MF")
    ('DF', 'MF')
    >>> split_positions("fw , mf")
    ('FW', 'MF')
    >>> split_positions(None)
    ()

    Los valores desconocidos se descartan en silencio: es preferible dejar la
    posicion vacia a asignar un grupo equivocado, porque el grupo determina
    contra quien se compara al jugador.
    """
    if not raw or not isinstance(raw, str):
        return ()

    groups: list[str] = []
    # Se acepta tanto el formato de FBref ("DF,MF") como el de Understat
    # ("D M S"): coma, barra o espacio separan igual.
    for token in raw.replace("/", ",").replace(" ", ",").split(","):
        limpio = token.strip().upper()
        if not limpio or limpio == SUBSTITUTE_MARKER:
            continue
        normalised = _ALIASES.get(limpio)
        if normalised and normalised not in groups:
            groups.append(normalised)
    return tuple(groups)


def primary_position(raw: str | None) -> str | None:
    """Grupo de posicion principal, o `None` si FBref no lo publica.

    FBref lista primero la posicion en la que el jugador ha jugado mas minutos,
    asi que la primera es la principal.
    """
    groups = split_positions(raw)
    return groups[0] if groups else None


def is_hybrid(raw: str | None) -> bool:
    """Si el jugador aparece en mas de un grupo de posicion.

    Util para senalar casos limite: un `DF,MF` puede ser un lateral que sube o
    un mediocentro que baja a la linea de tres, y su percentil dentro de `DF`
    hay que mirarlo con mas cuidado que el de un central puro.
    """
    return len(split_positions(raw)) > 1
