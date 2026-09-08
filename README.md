# Futbol Analytics

[![CI](https://github.com/diegosm2003-arch/proyecto_analista_futbol/actions/workflows/ci.yml/badge.svg)](https://github.com/diegosm2003-arch/proyecto_analista_futbol/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Licencia](https://img.shields.io/badge/licencia-MIT-4F9D69)

Plataforma personal de analitica de futbol sobre **LaLiga**, con las **Big 5 ligas
europeas** como poblacion de referencia. El objetivo no es solo mover datos: es
que cada analisis diga algo defendible sobre el juego.

## Que hace

1. **Percentiles por posicion.** Situa a cada jugador en su percentil frente a
   jugadores comparables de las Big 5 (no solo de LaLiga: la muestra por
   posicion seria demasiado pequena), con la vista filtrable a LaLiga.
   Visualizacion tipo *pizza chart* estilo FBref.
2. **Estilo de juego.** Clustering sobre metricas agregadas para agrupar equipos
   por estilo y jugadores por rol.
3. **Asistente conversacional** *(opcional, fase final)*. Chat con tool calling
   limitado a unos pocos endpoints de la API. Nunca genera SQL libre.

## Criterios de analisis

- Comparaciones **siempre dentro de posiciones y roles comparables**.
- Metricas **por 90 minutos**, salvo cuando lo relevante sea el volumen total.
- Umbral de **minutos minimos** (`MIN_MINUTES`, por defecto 450) para que los
  ratios por 90 no sean ruido. Con la temporada empezada baja automaticamente:
  en la jornada 4 nadie llega a 450 minutos y la plataforma saldria vacia.
- Preferencia por metricas con significado futbolistico (xG, xA, pases
  progresivos, PPDA, presion) sobre metricas vacias como "pases totales".

## Arquitectura

```
                     backend/                          frontend/
FBref  ->  ETL  ->  PostgreSQL  ->  FastAPI  --HTTP-->  Streamlit
                                       ^                    |
                                       +----- Ollama <------+
```

**Tres imagenes**: PostgreSQL (oficial), `backend` y `frontend`. El ETL reutiliza
la imagen del backend cambiando el entrypoint, porque comparte con la API el
catalogo, el esquema y la logica de analisis.

Reglas de frontera:

- **FastAPI es la unica via de acceso a los datos.** El frontend no lee
  PostgreSQL y ni siquiera instala el paquete del backend: solo habla HTTP. La
  CI falla si aparece un import que cruce esa linea.
- **El ETL es un job**, no un servicio permanente: vive en un profile de Compose.
- **Ollama solo llama a endpoints concretos** de la API, con tool calling acotado.

## Estructura

Dos proyectos Python independientes, cada uno con su `pyproject.toml`, su
`Dockerfile` y sus tests.

```
backend/          ETL, analisis y API. Lo unico que toca PostgreSQL.
  src/futbol_analytics/
    config.py           Ajustes via variables de entorno
    logging_config.py   Logging estructurado en JSON
    metrics.py          Catalogo de metricas: que se guarda y por que
    positions.py        Normalizacion de posiciones
    templates.py        Ejes del pizza chart por posicion
    db/                 Esquema de PostgreSQL y motor de conexion
    etl/                Extraccion (soccerdata), limpieza y carga
    analysis/           Percentiles y clustering (logica pura, sin BD)
    api/                FastAPI: routers, esquemas, repositorio y cache
  tests/                176 tests, sin dependencia de la base de datos

frontend/         Interfaz Streamlit. Solo habla HTTP con la API.
  src/futbol_front/
    config.py       Donde esta la API
    client.py       Cliente HTTP, sin Streamlit para poder testearlo
    presentation.py Preparacion de datos, sin matplotlib
    charts.py       Pizza chart (mplsoccer) y mapa de estilos
    state.py        Cliente compartido y cacheo
    views/          Una vista por area del dominio
  tests/                24 tests

docker-compose.yml
```

## Modelo de datos

Tres tablas, definidas en [`db/schema.py`](src/futbol_analytics/db/schema.py):

- **`player_season`**: una fila por *(liga, temporada, equipo, jugador)*. El
  equipo forma parte de la clave a proposito: un jugador traspasado en enero
  tiene una fila por etapa, porque su rendimiento en cada club es un hecho
  distinto y promediarlos ocultaria el cambio de contexto.
- **`team_season`**: una fila por *(liga, temporada, equipo, perspectiva)*, con
  `perspective` a `for` o `against`. La fila del rival es la que permite derivar
  indicadores que dependen de el, como una PPDA aproximada.
- **`etl_run`**: registro de cada carga, para poder atribuir un dato raro a una
  ejecucion concreta.

Las columnas de metricas **se generan desde el catalogo** de
[`metrics.py`](src/futbol_analytics/metrics.py), asi que esquema y catalogo no
pueden desincronizarse. Dos reglas:

- Se guardan **totales, nunca valores por 90**. El per-90 depende del umbral de
  minutos y de la poblacion de comparacion: es analisis, no un hecho.
- Un hueco de FBref queda **NULL, nunca cero**. Un cero afirmaria algo falso
  sobre el jugador.

### La limitacion de la posicion

FBref, a nivel de temporada, solo publica `GK` / `DF` / `MF` / `FW`. No separa
central de lateral ni mediocentro de mediapunta, y comparar un central con un
lateral en centros al area no produce un percentil informativo.

El esquema guarda `position_group` (lo que FBref da, verificable) y deja
`detailed_position` **nula hasta la fase de analisis**, donde el clustering de
roles la asignara a partir de metricas que el ETL ya carga: toques por zona del
campo, centros, duelos aereos y conducciones progresivas. Un central y un
lateral se separan solos en ese espacio, sin inventar una heuristica a ojo.

Mientras tanto, cualquier percentil dentro de `DF` mezcla ambos perfiles y hay
que leerlo con esa reserva.

## Ejecutar el ETL

### Primera carga

Antes de nada, comprobar que el catalogo de metricas casa con lo que FBref
publica hoy. FBref renombra columnas de vez en cuando y esto convierte ese fallo
en un diff legible en lugar de una depuracion a ciegas:

```bash
docker compose --profile etl run --rm etl --inspect --leagues "ESP-La Liga"
```

Revisa `data/fbref_columns.json`, corrige `metrics.py` si hace falta, y carga:

```bash
# LaLiga de la temporada en curso, para ver algo funcionando cuanto antes
docker compose --profile etl run --rm etl --leagues "ESP-La Liga"

# La carga que el producto necesita de verdad: las Big 5
docker compose --profile etl run --rm etl
```

> **Cargar solo LaLiga funciona, pero degrada los percentiles.** La poblacion de
> referencia son las cinco grandes ligas: con una sola, un lateral se compara
> contra unos 80 laterales en lugar de contra 400. El ETL avisa por log y la API
> lo indica en los `caveats` de cada perfil. Sirve para probar la cadena de
> extremo a extremo; no para sacar conclusiones.

### Carga programada

```bash
docker compose --profile scheduler up -d
```

Levanta un contenedor que ejecuta el ETL de forma periodica. Por defecto,
**martes y jueves a las 6:00 hora de Madrid**: las estadisticas de temporada
solo cambian cuando se juega una jornada, y FBref limita a una peticion cada 7
segundos, asi que cargar a diario seria castigarlo para nada.

| Variable | Por defecto | Que hace |
| --- | --- | --- |
| `ETL_SCHEDULE` | `0 6 * * tue,thu` | Cadencia, en formato cron |
| `SCHEDULE_TIMEZONE` | `Europe/Madrid` | Para que "el martes por la manana" no dependa del cambio de hora |
| `ETL_RUN_ON_START` | `false` | Cargar al levantar el contenedor, sin esperar al martes |

> **Los dias van por nombre, no por numero.** APScheduler numera `0 = lunes` y
> el cron de toda la vida usa `0 = domingo`. Escrito `0 6 * * 2,4` la carga
> caeria en miercoles y viernes, y el viernes es *antes* de la jornada. Hay un
> test que fija este comportamiento.

**No es `cron` del sistema sino un proceso Python**, por cuatro razones con esta
imagen: `python:3.11-slim` no trae `cron`; el contenedor corre como usuario sin
privilegios; `cron` no escribe en stdout, asi que se perderia el logging
estructurado justo en las ejecuciones que nadie mira; y `cron` no hereda el
entorno del contenedor, que es el fallo clasico de "funciona a mano y falla
programado".

Dos protecciones que hacen segura la automatizacion:

- **Candado sobre `etl_run`.** Dos cargas simultaneas no cargarian nada nuevo y
  duplicarian la presion sobre FBref. Una ejecucion que lleve mas de 3 horas en
  marcha se da por muerta, para que un contenedor caido no bloquee para siempre.
- **La temporada en curso nunca se lee del cache.** `soccerdata` guarda el HTML
  descargado, lo cual es perfecto para una temporada cerrada y catastrofico para
  la actual: la carga terminaria con exito cada martes devolviendo los datos de
  la primera descarga, sin ningun error que mirar. Se puede forzar con
  `--use-cache` para depurar sin volver a descargar.

Si la carga falla, se ve en `GET /health` (`last_etl_status`), en
`GET /meta/etl` con el historial completo, y como aviso en la barra lateral de
la interfaz. La fecha de la ultima carga *correcta* seguiria ahi, y por eso el
estado va aparte.

### Otros usos

```bash
docker compose --profile etl run --rm etl --seasons 2526   # una temporada concreta
docker compose --profile etl run --rm etl --dry-run        # descarga sin escribir
docker compose --profile etl run --rm etl --only teams     # solo equipos
```

La carga es un `UPSERT` sobre la clave natural: relanzarla actualiza, nunca
duplica. Importa porque FBref corrige datos a posteriori y la temporada en curso
se re-scrapea cada semana.

`--inspect` vuelca a `data/fbref_columns.json` las columnas que FBref publica
hoy, ya normalizadas, junto a las que el catalogo espera y las que faltan. FBref
renombra columnas de vez en cuando; esto convierte ese fallo en un diff legible
en lugar de una depuracion a ciegas dentro del contenedor.

## Analisis

Todo el paquete [`analysis/`](src/futbol_analytics/analysis/) son funciones puras
sobre DataFrames. No abre conexiones: la API lee PostgreSQL, llama a estas
funciones y cachea el resultado en memoria.

### Percentiles

**El orden importa:** el percentil se calcula contra la poblacion completa de las
Big 5 y solo despues se filtra la vista a LaLiga. Al reves, un lateral se
compararia contra 80 laterales en lugar de contra 400, y el numero diria mas del
ruido muestral que del jugador. La poblacion se agrupa por *(temporada, grupo de
posicion)*: cruzar temporadas es comparar con un futbol que ya no se juega.

El filtro de minutos se aplica **antes** de ordenar. Si en la poblacion entran
jugadores con 40 minutos, un delantero que marco en su unica aparicion aparece en
el percentil 99 y arrastra la distribucion de todos los demas.

Cada metrica se ofrece en dos normalizaciones:

- **Por 90 minutos**, la comparacion justa por defecto.
- **Ajustada por posesion** (`padj`), solo para las acciones defensivas. Un
  pivote de un equipo con el 65 % del balon tiene mucho menos tiempo para robar
  que uno de un equipo replegado; sin ajustar, el percentil defensivo premia
  jugar en un equipo malo. El ajuste escala al equipo que tendria el 50 %:
  `padj = p90 * 50 / (100 - posesion)`.

Se guardan las dos y la interfaz permite cambiar, porque el contraste entre ambas
es en si mismo un hallazgo: hay centrocampistas que parecen recuperadores de
elite hasta que se ajusta por posesion.

Las metricas de estilo (`higher_is_better=None`, como despejes o entradas por
tercio) no se invierten nunca: su percentil dice **donde** juega el jugador, no
si es bueno.

### Roles de jugador

Rellena la `detailed_position` que FBref no publica. Dos decisiones:

**Las features son proporciones, no volumenes.** En lugar de "entradas por 90" se
usa "que porcentaje de sus toques son en el ultimo tercio" o "cuantos de cada 100
pases son progresivos". Los volumenes llevan dentro el estilo del equipo, de modo
que dos laterales del mismo perfil caerian en clusters distintos solo porque uno
juega en un equipo que domina.

**Los roles se fijan desde el futbol y el algoritmo los rellena.** No se elige `k`
por silhouette: se parte de doce roles reconocibles (central de area, central de
progresion, lateral profundo, lateral de construccion, pivote posicional,
organizador, interior de llegada, mediapunta, delantero de area, delantero de
enlace, extremo de banda, extremo finalizador), se pide a K-means ese numero de
grupos y se empareja cada centroide con el rol al que mas se parece, con
asignacion optima para que ningun nombre se repita. El silhouette se calcula como
control de calidad, no como criterio. Un cluster que no sabes nombrar no sirve
para contar nada.

Cada grupo de posicion se agrupa por separado: en un unico espacio, K-means
gastaria sus clusters en separar centrales de delanteros, que es justo lo que ya
sabemos. Los porteros quedan fuera.

### Estilo de equipo

Al reves que en los roles, aqui **el contexto es el objeto de estudio**, asi que
las features son magnitudes con unidades: posesion, volumen de pase, progresion,
presencia en campo rival, volumen y calidad de tiro, altura de presion y una PPDA
aproximada.

Los estilos no se nombran de antemano: cada cluster se describe por sus dos
rasgos mas extremos ("dominio del balon, presion adelantada"). Los estilos cambian
de temporada en temporada y fijar una lista seria forzar la realidad.

> **Sobre la PPDA:** la canonica se limita al 60 % del campo rival, y FBref no
> publica el pase del rival por zonas. La que se calcula aqui son pases del rival
> por accion defensiva propia sobre todo el campo: ordena bien a los equipos, pero
> **no es comparable con la PPDA de otras fuentes**. Si hiciera falta la real,
> habria que anadir Understat como segunda fuente en el ETL.

## API

Es la **unica via de acceso a los datos**: ni Streamlit ni el chat tocan
PostgreSQL. Documentacion interactiva en `/docs`.

| Endpoint | Que devuelve |
| --- | --- |
| `GET /health` | Estado y `data_version` (marca de la ultima carga del ETL) |
| `GET /meta/catalog` | Temporadas, ligas y umbral de minutos |
| `GET /meta/metrics` | Catalogo de metricas y como hay que leerlas |
| `GET /meta/roles` | Los doce roles que asigna el clustering |
| `GET /meta/etl` | Historial de cargas: estado, filas y errores |
| `GET /meta/templates` | Ejes del pizza chart por posicion |
| `GET /players` | Busqueda con filtros por liga, posicion, rol y nombre |
| `GET /players/{player}/profile` | Perfil de percentiles, listo para el pizza chart |
| `GET /teams/styles` | Estilos de juego de la temporada |

### El orden de las operaciones

Cada peticion de perfil ejecuta esta secuencia, y el orden es lo que hace que los
numeros signifiquen algo:

1. Se traen **todos** los jugadores de la temporada, las Big 5 completas.
2. Se asignan roles con el clustering (necesita toda la poblacion: no se puede
   decidir si un defensa es central o lateral mirandolo solo a el).
3. Se calculan percentiles contra esa poblacion.
4. **Solo entonces** se filtra por jugador, liga o posicion.

Invertir los pasos 3 y 4 no da un error: da un numero que parece bueno y no lo es.

### Respuestas con contexto

El perfil no devuelve solo percentiles. Incluye `population_size` (un percentil
contra 40 jugadores y otro contra 400 no valen lo mismo) y una lista de
`caveats` con las advertencias de lectura: poblacion pequena, grupo `DF` que
mezcla centrales y laterales, jugador sin rol por falta de minutos. Van en la API
y no en la interfaz para que las vea tambien quien consuma los endpoints
directamente, incluido el futuro chat.

Dos parametros gobiernan la comparacion:

- `basis=per90` (por defecto) o `padj` para el ajuste por posesion.
- `population=position` (por defecto) o `role` para comparar dentro del rol en
  lugar del grupo de posicion. Mas fino, pero la poblacion se reduce a un cuarto.

Un jugador traspasado a mitad de temporada devuelve **409**, no una media: sus
numeros en cada club son hechos distintos y promediarlos ocultaria el cambio de
contexto. Hay que indicar `team`.

### Cache

Los percentiles y los clusters se calculan al vuelo y se cachean en memoria. La
clave incluye la `data_version`, es decir, la marca de la ultima carga correcta
del ETL: **cuando el ETL vuelve a cargar, la cache se invalida sola**. No hay TTL,
porque un TTL siempre acaba siendo o demasiado corto (recalcula sin necesidad) o
demasiado largo (sirve datos viejos despues de una carga, sin que nada lo
indique).

## Interfaz

Tres vistas en Streamlit, servidas siempre desde la API.

**Jugadores.** Buscador con filtros y pizza chart de percentiles. Los
conmutadores de normalizacion (por 90 / ajustado por posesion) y de poblacion
(posicion / rol) estan a la vista: comparar las dos versiones del mismo jugador
suele ser el hallazgo.

Se pueden **superponer dos jugadores** sobre los mismos ejes, que es el formato
que responde a la pregunta que de verdad se hace un analista: no "¿como es este
jugador?" sino "¿en que se diferencia de aquel?". Solo se ofrecen jugadores de
la misma posicion, porque los ejes dependen de ella, y una metrica que le falte
a uno de los dos se cae del grafico: dejarla vacia se leeria como que ese
jugador vale cero en ella.

Todos los graficos se **descargan en PNG**, para poder publicarlos sin recurrir
a una captura de pantalla.

**Estilo de equipo.** Mapa de posesion frente a presion, coloreado por cluster.
El eje vertical va invertido porque una PPDA baja significa presion alta, y
dejarlo sin invertir situaria a los equipos mas agresivos abajo.

**Como leerlo.** Que es un percentil, por que la poblacion son las Big 5 y las
tres advertencias que mas se malinterpretan.

### Los ejes del grafico son fijos

Doce metricas por posicion, agrupadas en ataque, posesion y defensa, definidas en
[`templates.py`](src/futbol_analytics/templates.py) y servidas por
`GET /meta/templates`.

Son fijas a proposito. Un selector libre de metricas convierte cada grafico en
uno distinto e impide comparar dos jugadores de un vistazo, que es justo para lo
que sirve un pizza chart. Doce es el limite de legibilidad: por encima, las
porciones son demasiado estrechas para leer la etiqueta.

Se sirven desde la API y no se hardcodean en Streamlit para que el chat de la
fase 6 use exactamente los mismos ejes.

**Los porteros no tienen grafico.** Del catalogo publico de FBref solo se cargan
tres metricas de porteria, y un pizza chart de tres porciones dice menos que una
tabla. Es una limitacion del dato, no una decision de diseno: se resolveria
anadiendo las tablas avanzadas de portero al ETL.

## Puesta en marcha

Requiere Docker. Solo se ejecuta en el equipo personal.

```bash
cp .env.example .env        # y ajustar POSTGRES_PASSWORD
docker compose up -d --build                # postgres + backend + frontend
docker compose --profile etl run --rm etl   # ejecuta el ETL y termina
docker compose --profile scheduler up -d    # carga programada, martes y jueves
docker compose --profile chat up -d ollama  # opcional, fase final
```

- API: <http://localhost:8000/docs>
- Interfaz: <http://localhost:8501>

`src/` se monta como volumen y la API arranca con `--reload`: editar el codigo
no obliga a reconstruir la imagen.

## Desarrollo sin Docker

```bash
# Backend
cd backend && python -m pip install -e ".[analysis,api,dev]" && python -m pytest

# Frontend
cd frontend && python -m pip install -e ".[dev]" && python -m pytest
```

200 tests en total. Ninguno necesita PostgreSQL: la logica de analisis es pura
sobre DataFrames y la API sustituye el acceso a datos por objetos en memoria.

Para trabajar sobre el ETL hace falta el extra `etl` del backend, que arrastra
`soccerdata`.

## Estado

Pasos 1 a 5 completados: infraestructura, esquema de datos, ETL, capa de
analisis, API e interfaz. Queda el paso 6, opcional: el chat con Ollama.

Nada de esto se ha ejecutado todavia contra datos reales: el ETL no se ha
lanzado nunca y la base de datos esta vacia.
