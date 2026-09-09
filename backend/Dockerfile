# syntax=docker/dockerfile:1
#
# Imagen del backend: ETL, analisis y API. Una sola imagen para los dos usos,
# porque comparten catalogo, esquema y logica de analisis. El servicio `etl` del
# docker-compose reutiliza esta misma imagen cambiando el entrypoint.
#
# NO lleva navegador. La fuente de datos es Understat, que se descarga con
# peticiones HTTP normales. Hubo una version de esta imagen con Google Chrome y
# Xvfb, necesarios para pasar el Cloudflare de FBref, que la engordaba de 1 a
# 2,1 GB; se quitaron al comprobar que FBref sirve vacias sus tablas avanzadas y
# dejar de usarlo. El lector `etl/fbref_pages.py` sigue en el codigo y sus tests
# no necesitan red, pero descargar de FBref exigiria volver a instalar el
# navegador.

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

# `tls_requests`, que usa Understat, descarga una libreria nativa la primera vez
# DENTRO de su propio paquete, que pertenece a root. Como el contenedor corre
# sin privilegios, en ejecucion no puede: falla con "Failed to download the
# required TLS library". Se baja aqui y se cede el directorio.
#
# La descarga se verifica en su propia capa: sin comprobarlo, una imagen a la
# que le falte el binario se construye en verde y el fallo aparece mucho
# despues, cuando el ETL no puede leer nada.
RUN python -c "import tls_requests; tls_requests.Client()" \
    && python -c "import pathlib, tls_requests; \
        directorio = pathlib.Path(tls_requests.__file__).parent / 'bin'; \
        assert any(directorio.iterdir()), 'falta la libreria TLS'" \
    && chown -R appuser \
        "$(python -c 'import pathlib, tls_requests; print(pathlib.Path(tls_requests.__file__).parent / "bin")')"

USER appuser
EXPOSE 8000

# Healthcheck sin curl: evita anadir paquetes de sistema a la imagen.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "futbol_analytics.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
