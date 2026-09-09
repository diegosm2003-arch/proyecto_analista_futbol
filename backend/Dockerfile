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
# necesita el paso de Cloudflare, que pulsa la casilla del captcha con PyAutoGUI
# y por tanto no funciona sin display.
#
# No se hace `apt-get autoremove` despues: se lleva por delante las dependencias
# de Chrome (libglib2.0-0, libxdamage1, xdg-utils...) y deja una imagen que
# construye en verde y no tiene navegador.
ENV CHROME_DEB=https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates xvfb \
    && wget -q -O /tmp/chrome.deb "$CHROME_DEB" \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -rf /tmp/chrome.deb /var/lib/apt/lists/* \
    && google-chrome --version

# Instalacion editable: en desarrollo el codigo se monta como volumen, asi que
# un cambio en src/ se refleja sin reconstruir la imagen.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install -e ".[etl,api,analysis,scheduler]" \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser /app

# Dos librerias descargan binarios en tiempo de ejecucion DENTRO de su propio
# paquete, que pertenece a root. Como el contenedor corre sin privilegios, en
# ejecucion no pueden: seleniumbase lo intenta tres veces y falla en cinco
# segundos, y tls_requests lanza "Failed to download the required TLS library".
#
# Se descargan aqui, como root y con Chrome ya instalado para que las versiones
# casen, y se ceden los directorios por si hay que renovarlos.
#
# Cada descarga se verifica en su propia capa: sin comprobarlo, una imagen a la
# que le falte un binario se construye en verde y el fallo aparece mucho
# despues, cuando el ETL "termina bien" sin haber traido nada.
RUN sbase get uc_driver \
    && python -c "import tls_requests; tls_requests.Client()" \
    && python -c "import pathlib, seleniumbase; \
        ruta = pathlib.Path(seleniumbase.__file__).parent / 'drivers' / 'uc_driver'; \
        assert ruta.exists(), 'falta el driver del navegador'" \
    && chown -R appuser \
        "$(python -c 'import pathlib, seleniumbase; print(pathlib.Path(seleniumbase.__file__).parent / "drivers")')" \
    && chown -R appuser \
        "$(python -c 'import pathlib, tls_requests; print(pathlib.Path(tls_requests.__file__).parent / "bin")')"

USER appuser
EXPOSE 8000

# Healthcheck sin curl: evita anadir paquetes de sistema a la imagen.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "futbol_analytics.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
