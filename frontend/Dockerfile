# syntax=docker/dockerfile:1
#
# Imagen de la interfaz. No instala el paquete del backend: la interfaz solo
# habla HTTP con la API, y esa frontera se hace explicita aqui.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install -e "." \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser /app

USER appuser
EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]

CMD ["streamlit", "run", "/app/src/futbol_front/main.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
