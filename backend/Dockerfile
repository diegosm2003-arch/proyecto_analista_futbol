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

# FBref esta detras de Cloudflare, asi que soccerdata 1.9 no descarga con
# peticiones HTTP: usa un Chrome real a traves de seleniumbase en modo
# "undetected". Sin navegador en la imagen, el ETL crea el lector, registra un
# error y no descarga nada.
#
# Se instala Chrome estable y no Chromium porque el modo undetected de
# seleniumbase esta pensado para el primero. Xvfb aporta la pantalla virtual que
# necesita el paso de resolucion de Cloudflare, que interactua con la ventana
# aunque se ejecute en modo headless.
# No se hace `apt-get autoremove` despues de instalar Chrome: se lleva por
# delante sus dependencias (libglib2.0-0, libxdamage1, xdg-utils...) y deja una
# imagen que construye en verde y no tiene navegador. Lo que ahorraria son unos
# megas al lado de los 400 que ocupa Chrome.
ENV CHROME_DEB=https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates xvfb \
    && wget -q -O /tmp/chrome.deb "$CHROME_DEB" \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -rf /tmp/chrome.deb /var/lib/apt/lists/* \
    # Verificacion dentro de la propia construccion: sin esto, una imagen sin
    # navegador se publica en verde y el fallo aparece mucho despues, cuando el
    # ETL "termina bien" sin haber descargado nada.
    && google-chrome --version

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
