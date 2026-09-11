"""Codigos de temporada.

`soccerdata` identifica las temporadas con cuatro digitos: "2627" es 2026/27.
Las ligas europeas arrancan en agosto y terminan en mayo, asi que el ano natural
no sirve para saber en que temporada estamos.
"""

from __future__ import annotations

from datetime import date

# Mes a partir del cual una fecha pertenece ya a la temporada que empieza. Julio
# y no agosto: en julio ya hay pretemporada y fichajes, y ninguna competicion de
# la temporada anterior sigue viva.
SEASON_START_MONTH = 7


def season_code(day: date) -> str:
    """Codigo de la temporada a la que pertenece una fecha.

    >>> season_code(date(2026, 9, 8))
    '2627'
    >>> season_code(date(2026, 3, 1))
    '2526'
    """
    inicio = day.year if day.month >= SEASON_START_MONTH else day.year - 1
    return f"{inicio % 100:02d}{(inicio + 1) % 100:02d}"


def current_season(today: date | None = None) -> str:
    """Temporada en curso."""
    return season_code(today or date.today())


def season_label(season: str) -> str:
    """Temporada en el formato con el que se habla de ella.

    El codigo de cuatro digitos es lo que espera la fuente, pero nadie dice
    "la dos seis dos siete": se dice 26/27. La barra ademas evita el otro
    problema del codigo crudo, que a primera vista parece un ano suelto o un
    identificador interno.

    >>> season_label("2627")
    '26/27'
    >>> season_label("raro")
    'raro'
    """
    if len(season) == 4 and season.isdigit():
        return f"{season[:2]}/{season[2:]}"
    return season
