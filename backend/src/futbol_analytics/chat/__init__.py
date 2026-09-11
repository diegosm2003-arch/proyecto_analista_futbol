"""Asistente conversacional sobre los datos cargados.

Vive en el backend y no en la interfaz por dos razones. La primera es que sus
herramientas son el mismo analisis que usa la API, asi que llamarlas
directamente evita un viaje HTTP por cada paso del razonamiento. La segunda es
que asi la interfaz mantiene su unica regla: hablar solo con la API.

El modelo es pequeno a proposito —3B, local, sin coste ni cuenta— y eso manda en
todo el diseno: cuatro herramientas como maximo, descripciones de una linea,
respuestas cortas y un tope de vueltas. Un modelo de este tamano no razona sobre
tablas; elige entre opciones bien delimitadas, y el trabajo esta en delimitarlas.
"""
