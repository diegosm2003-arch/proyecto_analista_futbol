# Backend

ETL, analisis y API de la plataforma. Es la **unica pieza que accede a
PostgreSQL**.

```
src/futbol_analytics/
  config.py           Ajustes via variables de entorno
  logging_config.py   Logging estructurado en JSON
  metrics.py          Catalogo de metricas: que se guarda y por que
  positions.py        Normalizacion de posiciones
  templates.py        Ejes del pizza chart por posicion
  db/                 Esquema de PostgreSQL y motor de conexion
  etl/                Extraccion (soccerdata), limpieza y carga
  analysis/           Percentiles y clustering (logica pura, sin BD)
  api/                FastAPI
```

Una sola imagen sirve para la API y para el ETL: comparten catalogo, esquema y
logica de analisis. El servicio `etl` del compose reutiliza la imagen cambiando
el entrypoint.

## Desarrollo

```bash
python -m pip install -e ".[analysis,api,dev]"
python -m pytest
python -m ruff check .
```

Los tests no necesitan PostgreSQL: la logica de analisis es pura sobre
DataFrames y la API sustituye el acceso a datos por objetos en memoria.

Para trabajar tambien sobre el ETL hace falta el extra `etl`, que arrastra
`soccerdata`.
