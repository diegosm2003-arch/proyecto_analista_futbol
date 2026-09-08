# syntax=docker/dockerfile:1
#
# Imagen del backend: ETL, analisis y API. Una sola imagen para los dos usos,
# porque comparten catalogo, esquema y logica de analisis. El servicio `etl` del
# docker-compose reutiliza esta misma imagen cambiando el entrypoint.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Instalacion editable: en desarrollo el codigo se monta como volumen, asi que
# un cambio en src/ se refleja sin reconstruir la imagen.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install -e ".[etl,api,analysis,scheduler]" \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser /app

USER appuser
EXPOSE 8000

# Healthcheck sin curl: evita anadir paquetes de sistema a la imagen.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "futbol_analytics.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
