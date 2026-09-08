# CLAUDE.md

Contexto permanente del proyecto para Claude Code. Este archivo se lee automáticamente al inicio de cada sesión.

## Qué es este proyecto

Plataforma personal de **analítica de fútbol** de LaLiga. No es un proyecto de ingeniería de datos genérico que "casualmente" usa datos de fútbol: es una herramienta de análisis deportivo, construida desde la mirada de un analista de fútbol que además domina el big data. Las decisiones deben tener sentido **futbolístico** primero y técnico después.

**Propósito y motivación.** El autor es un profesional de big data y un aficionado profundo al fútbol (además de baloncesto y tenis), con una base sólida de conocimiento del juego. El proyecto persigue tres objetivos entrelazados:
1. **Transición profesional** hacia el sector de la analítica deportiva (clubes, empresas de sportstech / datos deportivos, scouting), combinando su perfil técnico con su conocimiento del deporte.
2. **Portfolio técnico** público en GitHub que demuestre un stack realista de datos de principio a fin.
3. **Generación de contenido** en LinkedIn, X/Twitter, Medium/Substack y Kaggle, para darse a conocer y entrar poco a poco en la comunidad de football analytics.

**El proyecto es la carta de presentación de un analista de fútbol.** Por eso, tan importante como que el código funcione es que los análisis cuenten algo interesante sobre el juego: que un hallazgo sea defendible ante alguien que sabe de fútbol, no solo estadísticamente correcto.

## Enfoque como analista de fútbol

- **Piensa por posición y por rol.** Un central, un lateral, un mediocentro organizador y un extremo no se miden con las mismas métricas. Las comparaciones siempre son dentro de posiciones/roles comparables.
- **Métricas por 90 minutos** para comparar de forma justa a jugadores con distinto tiempo de juego, salvo cuando el volumen total sea lo relevante.
- **La población de referencia importa.** Los percentiles se calculan frente a las Big 5 ligas (no solo LaLiga) para tener una muestra robusta por posición; la vista se filtra luego a LaLiga.
- **Prioriza métricas con significado futbolístico** (xG, xA, pases progresivos, PPDA, acciones defensivas, presión) sobre métricas vacías o engañosas (p. ej. "pases totales" sin contexto).
- **Cuidado con las trampas del dato**: muestras pequeñas (pocos minutos), correlación vs. causalidad, y métricas que dependen mucho del estilo del equipo. Cuando un hallazgo pueda malinterpretarse, señálalo.
- **Cada análisis debería poder resumirse en una frase que a un aficionado avanzado le resulte interesante o sorprendente.** Ese es el criterio de valor, además del rigor estadístico.

**Es un proyecto personal, no de empresa.** Prioriza claridad, buenas prácticas y que el resultado sea mostrable y reproducible por terceros.

## Qué hace la plataforma

1. **Percentiles por posición**: sitúa a cada jugador/equipo en su percentil frente a una población de referencia (las Big 5 ligas europeas: LaLiga, Premier, Serie A, Bundesliga, Ligue 1), con la vista filtrable a LaLiga. Visualización tipo "pizza chart" estilo FBref.
2. **Estilo de juego**: clustering (K-means / jerárquico) sobre métricas agregadas para agrupar equipos por estilo y jugadores por rol.
3. **Asistente conversacional (opcional, fase final)**: chat que responde preguntas sobre los datos vía tool calling contra la API.

## Arquitectura

Cinco servicios en contenedores Docker, orquestados con un único `docker-compose.yml`:

- **ETL**: extracción (scraping con `soccerdata` sobre FBref/Understat) y limpieza con `pandas`.
- **PostgreSQL**: almacenamiento persistente de los datos limpios (volumen Docker).
- **FastAPI**: capa de servicio; expone percentiles y estilo como endpoints REST. Es la única vía de acceso a los datos.
- **Streamlit**: interfaz interactiva; consume SIEMPRE la API de FastAPI, nunca la base de datos directamente.
- **Ollama** (opcional): modelo pequeño local (Qwen2.5/Qwen3 3-4B) con tool calling limitado a 2-4 endpoints concretos de FastAPI. Nunca genera SQL libre.

Flujo de datos: `FBref/Understat → ETL → PostgreSQL → FastAPI → Streamlit`, con `Streamlit → Ollama → FastAPI` para el chat.

## Orden de desarrollo (respetar dependencias)

1. Infraestructura (Docker, repo, CI)
2. Datos (ETL → PostgreSQL)
3. Análisis (percentiles, clustering)
4. Capa de servicio (FastAPI)
5. Presentación (Streamlit)
6. Chat con Ollama (opcional, solo cuando la API esté estable)

No construir una capa antes de que exista aquello de lo que depende.

## Convenciones técnicas

- **Lenguaje**: Python 3.11+.
- **Estilo**: código limpio y legible; nombres descriptivos; funciones cortas con una responsabilidad clara.
- **Tests**: `pytest`. La lógica pura (cálculo de percentiles, clustering) debe testearse sin dependencia de la base de datos, con DataFrames de ejemplo.
- **Datos y modelos NUNCA en Git**: los datos scrapeados y los modelos de Ollama se ignoran en `.gitignore`; solo se versiona el código que los genera.
- **Configuración vía variables de entorno** (`.env`, ignorado en Git); nunca credenciales hardcodeadas.
- **Logging estructurado** en ETL y FastAPI; nada de `print()` para trazas.

## Contexto de trabajo en dos equipos

El código se escribe en dos ordenadores (trabajo y personal) sincronizados vía un repo privado de GitHub. El despliegue y la ejecución (Docker, Ollama, carga de datos) ocurren SOLO en el equipo personal. En el equipo del trabajo solo se edita código que no requiere ejecución (definiciones, lógica pura, tests unitarios, documentación).

## Qué hacer y qué no

- Explica las decisiones de diseño antes de implementarlas cuando no sean triviales.
- Prioriza soluciones simples y estándar sobre las sofisticadas: este proyecto ya tiene suficientes piezas nuevas que aprender.
- No introduzcas dependencias pesadas (Airflow, Kafka, dbt) sin discutirlo antes: se descartaron deliberadamente por sobreingeniería a esta escala.
- Cuando toques una capa, respeta su frontera (p. ej. no hagas que Streamlit lea PostgreSQL directamente).
- Ante una decisión de análisis (qué métrica usar, cómo agrupar, cómo visualizar), razona primero desde el fútbol: ¿esto le diría algo útil a un analista o a un aficionado avanzado? Si una elección es correcta estadísticamente pero pobre futbolísticamente, coméntalo.
