"""Logica de analisis: percentiles por posicion y clustering de estilo y rol.

Este paquete no habla con la base de datos: recibe y devuelve DataFrames, para
poder testearse sin infraestructura. La API es quien lee PostgreSQL, llama a
estas funciones y cachea el resultado en memoria.
"""

from futbol_analytics.analysis import features, percentiles, roles, style

__all__ = ["features", "percentiles", "roles", "style"]
