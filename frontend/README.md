# Frontend

Interfaz Streamlit. **Solo habla HTTP con la API**: no importa el paquete del
backend ni conoce PostgreSQL.

```
src/futbol_front/
  config.py       Donde esta la API (unica dependencia externa)
  client.py       Cliente HTTP, sin Streamlit para poder testearlo
  presentation.py Preparacion de datos de los graficos, sin matplotlib
  charts.py       Pizza chart (mplsoccer) y mapa de estilos
  state.py        Cliente compartido y cacheo de respuestas
  views/          Una vista por area del dominio
  main.py         Navegacion
```

La separacion entre `presentation` y `charts` es deliberada: las reglas (que
ejes, en que orden, que hacer con los huecos) quedan testeables sin instalar
matplotlib, y el dibujo es una capa fina encima.

## Configuracion

| Variable | Por defecto | Que hace |
| --- | --- | --- |
| `API_BASE_URL` | `http://backend:8000` | Direccion de la API |
| `API_TIMEOUT` | `20` | Segundos antes de dar una peticion por perdida |

## Desarrollo

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
streamlit run src/futbol_front/main.py
```
