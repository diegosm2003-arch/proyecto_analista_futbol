# 02 · Integraciones y fuentes de datos

Especificación de nuevas integraciones para ampliar la capacidad analítica de la plataforma.

> **Para Claude Code**: explora primero el repositorio para ver qué fuentes están ya ingeridas, qué tablas de FBref se descargan y cuáles no, y cómo está estructurado el ETL. Varias de estas integraciones probablemente solo requieran ampliar el pipeline existente, no crear uno nuevo. No añadas dependencias pesadas (Airflow, Kafka, dbt) — fueron descartadas deliberadamente por sobreingeniería a esta escala.

---

## PRIORIDAD 1 — Datos de tiro de Understat (shot-level)

**Qué desbloquea**: mapas de tiros, xG por zona, calidad media de ocasión, análisis de finalización real. Es el salto cualitativo más grande disponible sin coste ni fuente nueva.

**Por qué es lo primero**: Understat ya está integrado en la plataforma para datos agregados, pero expone además datos a nivel de tiro individual (coordenadas, xG del tiro, parte del cuerpo, tipo de jugada, resultado). Pasar de "este jugador tiene 0.35 npxG por 90" a "aquí es donde tira y con qué calidad" es la diferencia entre una herramienta de consulta y una herramienta de análisis.

**Implementación**:
- `soccerdata` expone lectura de eventos de tiro desde Understat. Revisar la API de la versión instalada (típicamente un método de lectura de shot events por liga/temporada).
- Nueva tabla en PostgreSQL: tiros individuales con `player_id`, `match_id`, coordenadas X/Y, xG, resultado, tipo de jugada, parte del cuerpo, minuto.
- Volumen: manejable (unos pocos cientos de miles de filas para Big 5 × 2 temporadas).

**Análisis que habilita**:
- **Mapa de tiros** del jugador con `mplsoccer` (`VerticalPitch` + scatter dimensionado por xG). Es el gráfico más icónico de la analítica de fútbol moderna.
- **Calidad media de ocasión** (xG por tiro): distingue al que genera pocas ocasiones buenas del que dispara mucho desde lejos.
- **Sobrerrendimiento en finalización** con contexto: goles − xG, pero ahora desglosado por zona, lo que permite ver si el sobrerrendimiento viene de un tipo concreto de remate.
- **Mapa de tiros concedidos** a nivel de equipo: dónde le rematan, complementa mucho el análisis de estilo defensivo.

---

## PRIORIDAD 2 — Match logs de FBref (datos por partido)

**Qué desbloquea**: análisis intra-temporada real (medias móviles, rachas, forma reciente), que hoy es imposible con datos agregados por temporada.

**Por qué**: resuelve la limitación estructural señalada en el documento 01 — con dos temporadas no hay evolución posible, pero con datos por jornada sí hay tendencia legítima dentro de cada temporada. Además permite responder "¿cómo está ahora?" frente a "¿cómo va la temporada?", que son preguntas distintas y ambas relevantes.

**Implementación**:
- FBref publica match logs por jugador y por equipo. `soccerdata` los expone (revisar métodos de lectura de match logs / player match stats).
- Nueva tabla: estadísticas por jugador y partido.
- Cuidado con el volumen de peticiones y el rate limiting de FBref: el scraping debe ser respetuoso con los tiempos de espera que `soccerdata` ya implementa. No paralelizar agresivamente.

**Análisis que habilita**:
- Media móvil de npxG, xA, acciones defensivas a lo largo de la temporada.
- Forma reciente (últimos 5 partidos) frente a media de temporada.
- Detección de cambios de rol tras un cambio de entrenador o de sistema.
- Gráficos de acumulado (goles vs xG acumulado a lo largo de la temporada) — un clásico muy legible.

---

## PRIORIDAD 3 — Explotación completa de Transfermarkt

**Estado**: ya integrado con histórico. Esta prioridad no es integrar, es **explotar** lo que ya está ahí.

**Campos que probablemente ya tienes o son accesibles y están infrautilizados**:
- **Fecha de fin de contrato**: habilita el caso de uso de scouting más práctico de todos — "jugadores con alto percentil en su posición y contrato expirando en menos de 12 meses". Esto es literalmente lo que hace un director deportivo. Si el campo no está ingerido, priorizarlo.
- **Nacionalidad y edad**: filtros esenciales para scouting realista.
- **Historial de traspasos**: importes, clubes, fechas. Habilita la trayectoria de carrera del documento 01.
- **Posición declarada en Transfermarkt**: útil como validación cruzada de la posición asignada desde FBref (las discrepancias son informativas: un jugador clasificado como MF en FBref pero como extremo en Transfermarkt suele indicar un rol híbrido).

**Advertencia de calidad de dato**: el emparejamiento de identidades FBref↔Transfermarkt vía fuzzy matching tiene falsos positivos. Toda vista que combine ambas fuentes debe poder indicar el nivel de confianza del emparejamiento, y los emparejamientos por debajo del umbral no deben mostrarse como si fueran ciertos.

---

## PRIORIDAD 4 — Compartir por URL (`st.query_params`)

**Qué desbloquea**: que cada análisis sea un enlace. Es la integración que conecta la plataforma con la estrategia de contenido en redes.

**Implementación**:
- Streamlit expone `st.query_params` para leer y escribir parámetros de URL.
- El estado de la vista (liga, temporada, jugador seleccionado, jugador de comparación, normalización, métrica del ranking) se serializa en la URL.
- Al cargar, la aplicación lee esos parámetros y reconstruye la vista.
- Botón "copiar enlace a este análisis".

**Por qué está en prioridad alta pese a no ser analítico**: multiplica el valor de todo lo demás. Un post en X con un gráfico y un enlace que lleva exactamente a esa vista convierte cada análisis en tráfico y demostración de la herramienta.

---

## PRIORIDAD 5 — Exportación de informes

**Dos formatos, dos propósitos**:

**A. PNG con marca para redes**
- Exportación del gráfico con el logotipo, el nombre de la plataforma y la fuente de datos ya incrustados.
- Dimensiones optimizadas para X/LinkedIn (proporción cercana a 16:9 o cuadrada).
- Ya existe "Descargar gráfico (PNG)" — la mejora es que salga con marca y metadatos, no desnudo.

**B. Informe PDF de jugador**
- Una página con: radar, detalle numérico, lecturas interpretadas, comparables y datos de mercado.
- Librería: `reportlab` o generación de HTML + `weasyprint`. Evaluar cuál encaja mejor con lo ya instalado.
- **Por qué importa**: convierte la plataforma en algo que un ojeador se llevaría a una reunión. Es la señal más fuerte de "esto es un producto, no un dashboard".

---

## PRIORIDAD 6 — Chat con Ollama (ya planificado)

Sin cambios respecto al diseño previo: modelo pequeño (Qwen2.5/Qwen3 3-4B) con tool calling limitado a 2-4 endpoints concretos de FastAPI, nunca SQL libre. Va al final, cuando la API esté estable.

**Refinamiento sobre el diseño original**: con las nuevas vistas, las herramientas naturales a exponer serían:
1. `obtener_percentiles_jugador(nombre, temporada)`
2. `comparar_jugadores(jugador_a, jugador_b)`
3. `buscar_jugadores(posicion, metrica, minimo_percentil, edad_max)`
4. `obtener_estilo_equipo(equipo, temporada)`

Descripciones de una línea cada una. Con más de cuatro herramientas o descripciones largas, un modelo de 3-4B empieza a fallar en la selección.

---

## Fuentes evaluadas y descartadas (por ahora)

| Fuente | Qué aportaría | Por qué se descarta ahora |
|---|---|---|
| StatsBomb Open Data | Datos de evento completos (pases, presiones, posicionamiento) | Cobertura limitada a competiciones concretas, no Big 5 actuales. Excelente para un proyecto paralelo de demostración técnica, no para la plataforma principal |
| Sofascore / WhoScored vía `soccerdata` | Divisiones inferiores españolas | Reservado para la ampliación a LaLiga 2 / Primera RFEF; requiere configuración de `league_dict.json`. Prioridad futura, no ahora |
| Wyscout / Opta / SkillCorner | Datos profesionales, tracking | Coste prohibitivo para proyecto personal |
| APIs de datos en vivo | Resultados en tiempo real | La plataforma es de análisis, no de seguimiento en directo. No aporta al caso de uso |
| FotMob | Mapas de calor | Scraping frágil y de legalidad dudosa; los datos de tiro de Understat cubren mejor la necesidad |

---

## Nota sobre automatización

Se mantiene la decisión previa: `cron` dentro del contenedor ETL cuando el pipeline sea estable. Con la incorporación de match logs y datos de tiro, la carga aumenta, por lo que conviene:
- Separar la actualización **incremental** (solo jornadas nuevas) de la **carga completa** (solo al añadir una temporada o fuente).
- No re-scrapear temporadas cerradas: 25/26 está completa y no cambia.
- Frecuencia recomendada: semanal, tras el cierre de la jornada.
