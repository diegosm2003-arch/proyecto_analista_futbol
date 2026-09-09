"""Integracion con Transfermarkt: valor de mercado y fichajes.

Transfermarkt no publica una API, asi que se usa un envoltorio open source
(`felipeall/transfermarkt-api`) que corre como un servicio mas del compose. El
ETL lo consume por nombre de servicio; nunca sale a Transfermarkt directamente.

El problema dificil de esta integracion no es descargar, es **saber de quien
estamos hablando**: Understat y Transfermarkt usan identificadores propios y no
comparten ninguno. Eso lo resuelve `matching`, y su resultado se guarda para no
repetirlo.
"""
