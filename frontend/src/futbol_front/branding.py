"""Logotipo del proyecto.

Vive en un fichero y no escrito en el codigo para que cambiarlo no sea tocar
Python: basta con dejar el definitivo en `assets/logo.svg`. Como `src` va montado
en el contenedor, el cambio se ve sin reconstruir la imagen.

Se admite SVG y PNG. El SVG se incrusta tal cual, que es lo que permite que el
trazo tome el color de la liga a traves de `currentColor`; un PNG se incrusta en
base64 y mantiene sus propios colores, que para un logotipo de marca suele ser
lo que se quiere.

Si no hay ningun fichero la interfaz no se rompe: se dibuja un hueco con las
iniciales. Un logotipo que falta no puede tumbar la cabecera de la aplicacion.
"""

from __future__ import annotations

import base64
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).parent / "assets"

# En orden de preferencia. El SVG primero porque escala sin pixelarse y puede
# heredar el color del tema.
#
# Para que un logotipo encaje con la interfaz:
#
# - **Lienzo cuadrado** (`viewBox="0 0 48 48"` o similar), porque el hueco de la
#   cabecera lo es y uno apaisado se deforma.
# - **`currentColor` en los trazos** que deban tomar el color de la liga. Lo que
#   lleve un color fijo se quedara igual en las cinco competiciones, que para un
#   logotipo de marca suele ser justo lo que se quiere.
#
# Esto se documenta aqui y no dentro del propio SVG a proposito: un comentario
# dentro del fichero acaba pintado en la portada, porque Streamlit pasa el HTML
# por su procesador de markdown.
CANDIDATOS = ("logo.svg", "logo.png")

# Hueco cuando no hay fichero. Las iniciales del proyecto sobre el acento.
_RESERVA = (
    '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" role="img" '
    'aria-label="Futbol Analytics">'
    '<rect width="48" height="48" rx="12" fill="currentColor" opacity="0.18"/>'
    '<text x="24" y="31" text-anchor="middle" font-size="19" font-weight="800" '
    'fill="currentColor" font-family="sans-serif">FA</text>'
    "</svg>"
)


@lru_cache(maxsize=1)
def logo_html(size_px: int = 40) -> str:
    """Logotipo listo para incrustar en la cabecera.

    Cacheado porque Streamlit reejecuta el script entero con cada clic y leer el
    fichero en cada pasada seria un acceso a disco por interaccion. El precio es
    que un cambio de logotipo necesita recargar la pagina, que para un fichero
    que se toca una vez es un cambio razonable.
    """
    for nombre in CANDIDATOS:
        ruta = ASSETS / nombre
        if not ruta.is_file():
            continue
        try:
            return _incrustar(ruta, size_px)
        except OSError as error:
            logger.warning(
                "No se ha podido leer el logotipo",
                extra={"fichero": str(ruta), "motivo": str(error)},
            )

    return _envolver(_RESERVA, size_px)


# Lo que hay que quitar de un SVG antes de incrustarlo: comentarios, la
# declaracion XML y el DOCTYPE.
_RUIDO_XML = re.compile(r"<!--.*?-->|<\?xml.*?\?>|<!DOCTYPE.*?>", re.DOTALL)


def _limpiar_svg(contenido: str) -> str:
    """Deja el SVG listo para incrustarlo dentro de un markdown.

    Hace falta porque Streamlit pasa el HTML por su procesador de markdown antes
    de pintarlo, y ahi un comentario XML no se ignora: sus lineas se interpretan
    como texto. Un comentario con guiones acaba convertido en una lista con
    vinetas encima del logotipo, que es exactamente lo que pasaba.

    No es un problema solo de nuestro fichero. Cualquier SVG exportado de Figma
    o de Illustrator viene con su comentario de generador, asi que el logotipo
    que se ponga manana romperia la portada igual si esto no estuviera.
    """
    return _RUIDO_XML.sub("", contenido).strip()


def _incrustar(ruta: Path, size_px: int) -> str:
    if ruta.suffix == ".svg":
        # Se incrusta el SVG en linea y no como <img src>: dentro de un <img> el
        # `currentColor` no resuelve, y el logotipo no tomaria el color de la
        # liga.
        return _envolver(_limpiar_svg(ruta.read_text(encoding="utf-8")), size_px)

    datos = base64.b64encode(ruta.read_bytes()).decode("ascii")
    imagen = f'<img src="data:image/png;base64,{datos}" alt="Futbol Analytics">'
    return _envolver(imagen, size_px)


def _envolver(contenido: str, size_px: int) -> str:
    return f'<div class="logotipo" style="width:{size_px}px;height:{size_px}px;">{contenido}</div>'
