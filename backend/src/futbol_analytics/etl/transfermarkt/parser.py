"""Normaliza lo que devuelve Transfermarkt a filas de nuestras tablas.

Funciones puras: entra el JSON tal cual, salen diccionarios listos para el
upsert. Es lo que permite probar el formato sin levantar el servicio ni salir a
la red, que es donde estan las sorpresas.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Sufijos que Transfermarkt usa cuando devuelve el importe como texto en lugar
# de como numero. Cual de las dos formas llega varia entre endpoints.
_MULTIPLICADORES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000}

# Textos que aparecen en el importe de un fichaje y no son una cifra.
_SIN_IMPORTE = {
    "free transfer": "libre",
    "loan transfer": "cesion",
    "loan fee": "cesion",
    "end of loan": "fin_cesion",
    "?": None,
    "-": None,
}


def parse_amount(value: object) -> float | None:
    """Convierte un importe de Transfermarkt a euros.

    Acepta las dos formas que devuelve el servicio: numero directo o texto con
    sufijo.

    >>> parse_amount(150000000)
    150000000.0
    >>> parse_amount("€12.00m")
    12000000.0
    >>> parse_amount("Free transfer") is None
    True
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    texto = str(value).strip().lower()
    if texto in _SIN_IMPORTE or not any(c.isdigit() for c in texto):
        return None

    limpio = texto.replace("€", "").replace(",", "").strip()
    coincidencia = re.match(r"^([\d.]+)\s*(bn|m|k)?$", limpio)
    if not coincidencia:
        logger.warning("Importe no reconocido", extra={"valor": str(value)})
        return None

    cantidad, sufijo = coincidencia.groups()
    try:
        return float(cantidad) * _MULTIPLICADORES.get(sufijo or "", 1)
    except ValueError:
        return None


def parse_date(value: object) -> date | None:
    """Convierte una fecha de Transfermarkt a `date`.

    >>> parse_date("2020-07-31")
    datetime.date(2020, 7, 31)
    >>> parse_date("Jul 31, 2020")
    datetime.date(2020, 7, 31)
    """
    if not value:
        return None
    texto = str(value).strip()
    for formato in ("%Y-%m-%d", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()  # noqa: DTZ007
        except ValueError:
            continue
    logger.warning("Fecha no reconocida", extra={"valor": texto})
    return None


def classify_transfer(entry: dict[str, Any]) -> str | None:
    """Deduce el tipo de operacion.

    Transfermarkt no siempre publica el importe, y sin el no se puede distinguir
    un traspaso de una cesion. Cuando no hay forma de saberlo se devuelve `None`
    en lugar de suponer "traspaso": una cesion contada como traspaso falsea
    cualquier analisis de gasto.
    """
    bruto = entry.get("fee")
    if bruto is None:
        return None

    texto = str(bruto).strip().lower()
    for marca, tipo in _SIN_IMPORTE.items():
        if marca in texto:
            return tipo

    return "traspaso" if parse_amount(bruto) else None


def parse_market_value_history(payload: dict[str, Any], understat_id: str) -> list[dict[str, Any]]:
    """Convierte el historico de valor de mercado en filas."""
    filas = []
    for punto in payload.get("marketValueHistory") or []:
        fecha = parse_date(punto.get("date"))
        if fecha is None:
            continue
        filas.append(
            {
                "understat_id": understat_id,
                "valuation_date": fecha,
                "market_value_eur": parse_amount(punto.get("marketValue")),
                "club_at_time": punto.get("clubName"),
                "age_at_time": _entero(punto.get("age")),
            }
        )
    return filas


def clubs_in_history(payload: dict[str, Any]) -> list[str]:
    """Clubes por los que ha pasado un jugador, segun su historico de tasaciones.

    Sirve para confirmar una identidad dudosa: la busqueda solo devuelve el club
    ACTUAL, pero la carrera entera dice si ese futbolista estuvo alguna vez en el
    equipo que estamos cargando.
    """
    historico = payload.get("marketValueHistory") or []
    return [str(p["clubName"]) for p in historico if p.get("clubName")]


def parse_transfers(payload: dict[str, Any], understat_id: str) -> list[dict[str, Any]]:
    """Convierte el historial de fichajes en filas.

    Se descartan los movimientos anunciados y aun no efectivos (`upcoming`): un
    fichaje que todavia no ha ocurrido no pertenece al historial, y ademas puede
    caerse.
    """
    filas = []
    for entrada in payload.get("transfers") or []:
        if entrada.get("upcoming"):
            continue
        fecha = parse_date(entrada.get("date"))
        origen = (entrada.get("clubFrom") or {}).get("name")
        destino = (entrada.get("clubTo") or {}).get("name")
        # Los tres forman la clave: sin ellos la fila no se puede insertar ni
        # identificar despues.
        if not (fecha and origen and destino):
            continue

        filas.append(
            {
                "understat_id": understat_id,
                "transfer_date": fecha,
                "club_from": origen,
                "club_to": destino,
                "fee_eur": parse_amount(entrada.get("fee")),
                "transfer_type": classify_transfer(entrada),
                "market_value_at_transfer_eur": parse_amount(entrada.get("marketValue")),
                "season": entrada.get("season"),
            }
        )
    return filas


def parse_squad_player(entry: dict[str, Any], understat_id: str) -> dict[str, Any]:
    """Convierte la ficha de un jugador de la plantilla en una fila.

    Es contexto, no rendimiento, y por eso importa: un percentil 95 no significa
    lo mismo a los 19 anos que a los 33, ni en un jugador al que le queda un ano
    de contrato que en uno atado hasta 2031.
    """
    nacionalidades = entry.get("nationality") or []
    return {
        "understat_id": understat_id,
        "transfermarkt_id": str(entry.get("id")) if entry.get("id") else None,
        "player_name": entry.get("name"),
        "date_of_birth": parse_date(entry.get("dateOfBirth")),
        "age": _entero(entry.get("age")),
        "position": entry.get("position"),
        # Se guarda la primera: es la que Transfermarkt considera principal, y
        # una lista no cabe en una columna sin inventarse un formato.
        "nationality": nacionalidades[0] if nacionalidades else None,
        "height_cm": _entero(entry.get("height")),
        "foot": entry.get("foot"),
        "joined_on": parse_date(entry.get("joinedOn")),
        "signed_from": entry.get("signedFrom"),
        "contract_until": parse_date(entry.get("contract")),
    }


def _entero(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
