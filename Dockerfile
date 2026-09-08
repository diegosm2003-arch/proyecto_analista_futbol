# syntax=docker/dockerfile:1
#
# Un unico Dockerfile multi-stage para los tres servicios Python.
# La base es identica; cada stage instala solo los extras que necesita.
# docker-compose selecciona el stage con `build.target`.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Instalacion editable: el codigo se monta como volumen en desarrollo, asi que
# un cambio en src/ se refleja sin reconstruir la imagen.
COPY pyproject.toml README.md ./
COPY src ./src

RUN useradd --create-home --uid 1000 appuser


# --- ETL: job por lotes, se ejecuta y termina -------------------------------
FROM base AS etl
RUN pip install -e ".[etl,analysis]"
USER appuser
# ENTRYPOINT y no CMD: asi `docker compose run --rm etl --seasons 2526` anade
# argumentos a la CLI del ETL en lugar de reemplazar el comando entero.
ENTRYPOINT ["python", "-m", "futbol_analytics.etl"]
CMD []


# --- API: capa de servicio --------------------------------------------------
FROM base AS api
RUN pip install -e ".[api,analysis]"
USER appuser
EXPOSE 8000
# Healthcheck sin curl: evita anadir paquetes de sistema a la imagen.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
CMD ["uvicorn", "futbol_analytics.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- App: interfaz Streamlit ------------------------------------------------
FROM base AS app
RUN pip install -e ".[app]"
USER appuser
EXPOSE 8501
CMD ["streamlit", "run", "/app/src/futbol_analytics/app/main.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
