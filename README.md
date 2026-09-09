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
Understat  ->  ETL  ->  PostgreSQL  ->  FastAPI  --HTTP-->  Streamlit
                                           ^                    |
                                           +----- Ollama <------+
```

**La fuente es Understat, no FBref.** El proyecto nacio sobre FBref y hubo que
cambiarlo: FBref sirve vacias sus tablas avanzadas (comprobado en 2023/24,
2024/25 y 2025/26, cero valores en 1.314 celdas de pases completados) y ademas
exige pasar un Cloudflare con navegador. Understat publica la familia xG
completa, da un identificador estable de jugador y se descarga con peticiones
HTTP normales, asi que el ETL corre dentro del contenedor.

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

Definidas en [`db/schema.py`](src/futbol_analytics/db/schema.py). Tres tablas
del ETL principal:

- **`player_season`**: una fila por *(liga, temporada, equipo, jugador)*. El
  equipo forma parte de la clave a proposito: un jugador traspasado en enero
  tiene una fila por etapa, porque su rendimiento en cada club es un hecho
  distinto y promediarlos ocultaria el cambio de contexto.
- **`team_season`**: una fila por *(liga, temporada, equipo, perspectiva)*, con
  `perspective` a `for` o `against`. La fila del rival es la que permite derivar
  indicadores que dependen de el, como una PPDA aproximada.
- **`etl_run`**: registro de cada carga, para poder atribuir un dato raro a una
  ejecucion concreta.

Y cuatro de Transfermarkt, que van por su cuenta:

- **`player_id_mapping`**: el puente entre las dos fuentes, con la puntuacion del
  cruce y si alguien lo ha confirmado a mano.
- **`player_market_value`**: una fila por *(jugador, fecha de tasacion)*. Se
  guarda el historico entero, no el valor de hoy: la curva de valor de un
  canterano dice mas que su cifra actual.
- **`player_transfers`**: una fila por *(jugador, fecha, club de origen, club de
  destino)*.
- **`team_market_value`**: el valor de plantilla, **derivado** sumando el de sus
  jugadores en lugar de scrapearse aparte, para que siempre cuadre con la
  plantilla que tenemos cargada.

Las columnas de metricas **se generan desde el catalogo** de
[`metrics.py`](src/futbol_analytics/metrics.py), asi que esquema y catalogo no
pueden desincronizarse. Dos reglas:

- Se guardan **totales, nunca valores por 90**. El per-90 depende del umbral de
  minutos y de la poblacion de comparacion: es analisis, no un hecho.
- Un hueco de la fuente queda **NULL, nunca cero**. Un cero afirmaria algo
  falso sobre el jugador.

### La limitacion de la posicion

Understat, a nivel de temporada, solo publica `GK` / `DF` / `MF` / `FW`. No
separa central de lateral ni mediocentro de mediapunta, y comparar un central
con un lateral en centros al area no produce un percentil informativo. Ademas
marca a 71 jugadores solo como suplentes (`S`), que se quedan sin grupo.

El esquema guarda `position_group` (lo que la fuente da, verificable) y deja
`detailed_position` **nula hasta la fase de analisis**, donde el clustering de
roles la asignara a partir de metricas que el ETL ya carga: toques por zona del
campo, centros, duelos aereos y conducciones progresivas. Un central y un
lateral se separan solos en ese espacio, sin inventar una heuristica a ojo.

Mientras tanto, cualquier percentil dentro de `DF` mezcla ambos perfiles y hay
que leerlo con esa reserva.

## Ejecutar el ETL

### Primera carga

```bash
# LaLiga de la temporada en curso, para ver algo funcionando cuanto antes
docker compose --profile etl run --rm etl --leagues "ESP-La Liga"

# La carga que el producto necesita: las cinco grandes ligas
docker compose --profile etl run --rm etl
```

Las Big 5 de una temporada son unos **2.800 jugadores**, de los que cerca de
2.000 superan el umbral de minutos. Esa es la poblacion contra la que se
calculan los percentiles.

> **Cargar solo LaLiga funciona, pero degrada los percentiles.** Con una sola
> liga, un centrocampista se compara contra unos 120 en lugar de contra 427. El
> ETL avisa por log y la API lo indica en los `caveats` de cada perfil.

### Carga programada

```bash
docker compose --profile scheduler up -d
```

Levanta un contenedor que ejecuta el ETL de forma periodica. Por defecto,
**martes y jueves a las 6:00 hora de Madrid**: las estadisticas de temporada
solo cambian cuando se juega una jornada, asi que cargar a diario multiplicaria
por siete las peticiones a Understat para uno o dos cambios reales.

Con el perfil levantado tambien se programa **la carga de Transfermarkt, los
sabados a las 5:00**. Va a otro ritmo y otro dia a proposito: una tasacion se
revisa unas pocas veces al ano, y ademas esa carga lee `player_season` para
saber a quien buscar, asi que hacerlo mientras el ETL reescribe esa tabla daria
una plantilla a medias.

| Variable | Por defecto | Que hace |
| --- | --- | --- |
| `ETL_SCHEDULE` | `0 6 * * tue,thu` | Cadencia, en formato cron |
| `SCHEDULE_TIMEZONE` | `Europe/Madrid` | Para que "el martes por la manana" no dependa del cambio de hora |
| `ETL_RUN_ON_START` | `false` | Cargar al levantar el contenedor, sin esperar al martes |
| `TRANSFERMARKT_SCHEDULE` | `0 5 * * sat` | Cadencia del valor de mercado. Vacio para no programarlo |
| `TRANSFERMARKT_FRESHNESS_HOURS` | `720` | Cuanto se da por fresca una tasacion: treinta dias |

> **Levantalo en un solo equipo.** El candado que impide dos cargas simultaneas
> vive dentro de la base de datos, asi que no protege entre maquinas: dos
> planificadores activos consultarian las fuentes el doble sin traer nada nuevo.

> **La temporada se resuelve en cada ejecucion, no al arrancar.** Es la
> diferencia entre este proceso y un comando: vive semanas y cruza el cambio de
> temporada de julio. Resolviendola al arrancar —que es lo que hacia—, un
> planificador levantado en junio seguiria cargando la temporada anterior en
> septiembre e informando `success` cada martes, sin ningun error que mirar. Una
> temporada escrita a mano en `SEASONS` manda siempre; la que se calcula sola se
> recalcula cada vez.

> **La ventana de frescura son treinta dias, no siete.** Con la carga de
> Transfermarkt programada cada sabado, una ventana de una semana volveria a
> descargar la liga entera en cada ejecucion —miles de peticiones— para traer un
> dato que cambia trimestralmente. Con treinta dias, cada ejecucion refresca la
> parte que toca y el conjunto se renueva solo, repartido en el tiempo.
>
> La ficha del jugador (edad, posicion, contrato) **no pasa por esa ventana**:
> viene incluida en la plantilla, no cuesta una peticion aparte, y se actualiza
> en cada ejecucion.

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
  duplicarian la presion sobre la fuente. Una ejecucion que lleve mas de 3 horas en
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
duplica. Importa porque las fuentes corrigen datos a posteriori y la temporada en curso
se re-scrapea cada semana.

`--inspect` vuelca a `data/fbref_columns.json` las columnas que FBref publica
hoy, ya normalizadas, junto a las que el catalogo espera y las que faltan. FBref
renombra columnas de vez en cuando; esto convierte ese fallo en un diff legible
en lugar de una depuracion a ciegas dentro del contenedor.

## Valor de mercado y fichajes

```bash
docker compose --profile transfermarkt up -d          # el servicio de consulta
docker compose --profile transfermarkt --profile etl run --rm   --entrypoint python etl -m futbol_analytics.etl.transfermarkt --season 2526
```

Transfermarkt no publica API, asi que se consulta a traves de un envoltorio
open source levantado como un servicio mas. Anade dos cosas que el dato
deportivo no da: **cuanto vale un jugador y por donde ha pasado**. Un percentil
alto en un jugador de 30 millones y en uno de 3 no significan lo mismo.

### El problema de verdad es cruzar los nombres

Las dos fuentes no comparten ningun identificador, y el nombre es un
identificador pesimo en futbol: cada web elige una grafia, los acentos van y
vienen, y hay homonimos. El cruce
([`matching.py`](src/futbol_analytics/etl/transfermarkt/matching.py)) se apoya
en tres reglas:

- **Se comparan nombres normalizados** (sin acentos, sin puntuacion) con
  `token_sort_ratio`, porque el orden de nombre y apellido cambia entre fuentes.
- **El club desempata, pero no manda.** La busqueda devuelve el club *actual*, y
  nosotros cargamos temporadas pasadas: en septiembre de 2026 Transfermarkt
  situa a Lewandowski en el Chicago Fire. Penalizar eso mandaba a revision
  manual cruces evidentes.
- **Cuando hay empate se mira la carrera.** Si dos futbolistas comparten nombre
  al 100 %, se consulta el historico de tasaciones de cada uno: solo uno habra
  jugado en el equipo que estamos cargando. Es lo que resuelve a Lewandowski sin
  intervencion humana.

Un cruce por debajo de la confianza **no se descarta ni se usa**: se guarda sin
revisar y queda fuera de la carga. Cargar el valor de mercado de otra persona es
peor que no tener el dato.

```bash
# Los que esperan confirmacion
docker compose --profile transfermarkt --profile etl run --rm   --entrypoint python etl -m futbol_analytics.etl.transfermarkt --pendientes
```

Sobre la plantilla del Barcelona 2025/26: **26 de 29 jugadores resueltos sin
intervencion**. Los tres restantes son ambiguedad real —dos canteranos con
homonimos en clubes portugueses y un apodo (`Alex Balde` frente a `Alejandro
Balde`)—, exactamente los casos que deben esperar a una persona.

> **El valor de plantilla solo se publica si esta tasada.** Por debajo del 70 %
> de la plantilla no se guarda nada. Una suma parcial no es un valor bajo, es un
> valor falso: cargando solo el Barcelona aparecia el PSG valorado en 10 M
> porque uno de sus futbolistas habia jugado antes alli.

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

Rellena la `detailed_position` que la fuente no publica. Dos decisiones:

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

> **Sobre la PPDA:** la canonica se limita al 60 % del campo rival, y la fuente no
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
| `GET /meta/roles` | Los cuatro perfiles ofensivos que asigna el clustering |
| `GET /meta/etl` | Historial de cargas: estado, filas y errores |
| `GET /meta/templates` | Ejes del pizza chart por posicion |
| `GET /players` | Busqueda con filtros por liga, posicion, rol y nombre |
| `GET /players/{player}/profile` | Perfil de percentiles, listo para el pizza chart |
| `GET /teams/styles` | Estilos de juego de la temporada |

### Mercado y carrera

`GET /players/{jugador}/market` devuelve la ficha de Transfermarkt (edad,
posicion concreta, pie, contrato), la curva completa de valor de mercado y la
carrera del futbolista.

Va **aparte del perfil de percentiles** a proposito: son dos fuentes distintas y
una puede faltar sin que la otra deje de servir. Un jugador recien llegado a la
liga tendra percentiles y quiza aun no cruce con Transfermarkt.

Lo que anade es el contexto que a un percentil le falta. Un percentil 95 no
significa lo mismo a los 19 anos que a los 33, ni en alguien a quien le queda un
ano de contrato que en alguien atado hasta 2031. Y la **curva** dice mas que la
cifra: distingue al canterano en subida del veterano en caida aunque hoy valgan
lo mismo, y por eso la respuesta avisa cuando el valor actual esta por debajo
del maximo historico.

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

**Estilo de equipo.** Mapa de **territorio frente a presion**, coloreado por
cluster. El eje horizontal es cuanto campo pisa un equipo de verdad —llegadas a
zona de remate por partido— y no la posesion, que Understat no publica. Es
ademas un plano mas informativo: acumular pases y pisar el area rival no son lo
mismo, y hay equipos que hacen lo primero sin lo segundo.
El eje vertical va invertido porque una PPDA baja significa presion alta, y
dejarlo sin invertir situaria a los equipos mas agresivos abajo.

**Como leerlo.** Que es un percentil, por que la poblacion son las Big 5 y las
tres advertencias que mas se malinterpretan.

### Como esta organizada

Se entra por una **portada** donde se elige ambito —jugadores o equipos— y se
dice con que datos se esta trabajando, antes de que nadie lea un percentil sin
saber contra quien esta calculado. En las pantallas de trabajo esa explicacion
estorbaria; ahi es lo primero que se lee.

Dentro, **los filtros van arriba**. Son lo que define lo que se esta mirando y
se cambian constantemente: tenerlos en la misma linea de vision que el resultado
evita el salto de ojo a un lateral que el resto del tiempo esta vacio. La barra
lateral queda para lo que se consulta de vez en cuando: de que carga vienen los
datos.

**El tema cambia con la liga.** No es decoracion: un analista alterna entre
competiciones y el acento le dice de un vistazo en cual esta. Cambia el color,
nunca la disposicion, para que dos capturas de ligas distintas sigan siendo
comparables.

**El grafico y su lectura van uno al lado del otro.** El pizza chart ensena ocho
ejes a la vez y no dice por donde empezar; el panel de la derecha responde a eso
sin obligar a bajar. Por eso el grafico se dibuja mas pequeno de lo habitual:
caben los dos, pero solo si el circulo no ocupa la pantalla entera.

### Jugadores similares

Debajo del perfil, quien mas juega asi dentro de su mismo grupo posicional. Es
la pregunta con la que sigue un scout despues de ver un perfil que le gusta.

Se compara el **vector de percentiles**, no los valores por 90: cada metrica
tiene su escala y con valores crudos la distancia la mandaria la de numeros mas
grandes. La distancia es euclidea y no coseno a proposito, porque el coseno mira
la forma del perfil e ignora el nivel: un delantero del percentil 95 en todo
saldria identico a uno del percentil 30 en todo, que es justo lo contrario de lo
que un scout necesita.

Dos graficos, porque responden a cosas distintas. Las **barras** dicen *cuanto*
se parecen; el **plano** dice *por donde*. Dos jugadores con el mismo porcentaje
pueden estar uno arriba y otro a la derecha, y esa diferencia lo es todo.

Solo entran las metricas de aportacion. Las tarjetas quedan fuera porque casi
ningun futbolista ve una roja en una temporada: ese eje daba a toda la poblacion
por identica e inflaba el parecido de todos, y ademas salia como explicacion
—"se parecen en tarjetas rojas"— tapando lo que de verdad los acercaba.

### Donde se sale de lo normal

Un pizza chart ensena doce ejes a la vez y no dice por donde empezar. Debajo del
grafico, la interfaz senala las metricas en las que el jugador esta por encima
del percentil 90 o por debajo del 10, lo mas extremo primero. Es la pregunta que
se hace un analista delante de un perfil: que tiene este jugador de
verdaderamente distinto.

**Un extremo no siempre es bueno ni malo**, y por eso hay tres etiquetas:

- **Fortaleza** y **debilidad**, para las metricas con direccion.
- **Rasgo**, para las de estilo. Estar en el percentil 97 de tiros no es un
  elogio, es disparar mucho; si acierta o no lo dicen las metricas de
  finalizacion, no esa.

Fue precisamente este aviso el que dejo a la vista un error del catalogo: las
tarjetas estaban como "menos es mejor", asi que la interfaz presentaba *pocas
amarillas* como una **fortaleza** de Pedri, por delante de sus pases clave. Las
tarjetas no miden calidad, describen como compite un jugador: dar por mejor al
que menos ve premiaria al pivote que no hace la falta tactica y al central que
no sale a cortar. Ahora van sin direccion.

Dos matices acompanan al aviso cuando tocan:

- **Metricas que miden al equipo tanto como al jugador.** xGChain y xGBuildup
  cuentan posesiones, y un equipo que tiene el balon las genera para todos los
  suyos. En nuestros datos, tras De Jong y Pedri, los siguientes en xGBuildup
  son la defensa del Barcelona entera. El catalogo las marca `team_dependent` y
  el aviso lo dice.
- **Poblacion pequena.** Por debajo de 50 jugadores comparables, el percentil se
  mueve demasiado como para construir nada encima.

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

**Los porteros no tienen grafico.** Del catalogo publico de la fuente solo se cargan
tres metricas de porteria, y un pizza chart de tres porciones dice menos que una
tabla. Es una limitacion del dato, no una decision de diseno: se resolveria
anadiendo las tablas avanzadas de portero al ETL.

## Puesta en marcha

Requiere Docker.

```bash
cp .env.example .env        # y ajustar POSTGRES_PASSWORD
docker compose up -d --build                # postgres + backend + frontend
docker compose --profile etl run --rm etl   # ejecuta el ETL y termina
docker compose --profile scheduler up -d    # carga programada, martes y jueves
docker compose --profile chat up -d ollama  # opcional, fase final
```

### Trabajar en dos equipos

El repositorio se edita en dos ordenadores y los dos pueden levantar la
plataforma. **Git sincroniza el codigo, no los datos**: el volumen `pgdata` es
local a cada maquina, y el cache de scraping (`./data`) y el `.env` estan
ignorados.

Dos consecuencias:

- Hay que **cargar los datos en cada equipo**, o mover un volcado con
  `pg_dump`. Dos bases cargadas en dias distintos pueden diferir, porque las fuentes
  corrige datos a posteriori.
- **El planificador debe correr en un solo equipo.** El candado sobre
  `etl_run` vive en la base de datos y no protege entre maquinas: dos
  planificadores activos consultarian las fuentes el doble sin traer nada nuevo.

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

Pasos 1 a 5 completados y **ejecutados contra datos reales**: infraestructura,
esquema, ETL, analisis, API e interfaz, con las cinco grandes ligas de la
temporada 2026/27 cargadas desde Understat y, para LaLiga, la ficha, el valor de
mercado y la carrera de 356 futbolistas desde Transfermarkt. Queda el paso 6, opcional:
el chat con Ollama.

Lo que la plataforma **no** puede hacer hoy, y conviene saberlo antes de leer un
perfil:

- **No hay una sola metrica defensiva.** Understat no publica entradas,
  intercepciones ni despejes, asi que a un central solo se le juzga con balon.
  Es la limitacion mas seria que arrastra el proyecto.
- **La posicion concreta esta cargada pero aun no se usa para comparar.**
  Transfermarkt da "Centre-Back", "Left Winger" o "Central Midfield" donde
  Understat solo da `DF`, y eso se guarda ya en `player_profile`. Falta el paso
  siguiente: que la poblacion de referencia pueda ser esa y no el grupo de
  cuatro letras. Es la mejora con mas recorrido futbolistico que queda
  pendiente, porque comparar a un central con un lateral es justo lo que hoy
  distorsiona los percentiles de la defensa.
- **Los porteros no tienen metricas propias**, y por tanto no tienen grafico.
- **El ajuste por posesion no se aplica a nada.** La maquinaria existe, pero
  ninguna metrica de Understat es del tipo que ese ajuste corrige (divide por el
  tiempo *sin* balon, que es lo que necesita una metrica defensiva).
