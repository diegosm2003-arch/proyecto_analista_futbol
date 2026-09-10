# 01 · Visualización

Especificación de nuevos gráficos y mejoras de los existentes para la plataforma de analítica de fútbol.

> **Para Claude Code**: antes de implementar nada, explora el repositorio para entender las convenciones existentes (estructura de `src/`, cómo se construyen los gráficos actuales, cómo Streamlit consume la API de FastAPI, qué endpoints existen ya). Adapta estas especificaciones al código existente; no propongas reescrituras. Implementa un gráfico por vez, en el orden de prioridad indicado, y valida cada uno antes de pasar al siguiente.

## Contexto de datos disponible

- **Temporadas**: 25/26 y 26/27 (en curso).
- **Ligas**: Big 5 (Premier, LaLiga, Serie A, Bundesliga, Ligue 1).
- **Fuentes**: FBref y Understat vía `soccerdata`; Transfermarkt (valores de mercado e histórico) vía `felipeall/transfermarkt-api`.
- **Población de referencia para percentiles**: siempre Big 5; la liga es solo un filtro de visualización.

**Implicación crítica**: dos temporadas NO permiten curvas de evolución ni curvas de edad fiables. Sí permiten comparación entre dos puntos (25/26 vs 26/27). Cualquier gráfico que insinúe una tendencia con dos puntos es engañoso y debe evitarse. Esto se detalla en el gráfico 4.

---

## Principios de diseño de gráficos para este proyecto

Estos principios aplican a todo lo que se implemente:

1. **Cada gráfico responde a una pregunta futbolística concreta.** Si no se puede formular la pregunta en una frase que interese a un aficionado avanzado, el gráfico no entra.
2. **El percentil nunca va solo.** Siempre acompañado de: valor bruto, minutos jugados y población de comparación (n).
3. **Paleta segura para daltonismo.** Sustituir la paleta actual de clusters (verde/azul/rosa/verde claro/amarillo) por una paleta accesible. Recomendación: Okabe-Ito (`#E69F00`, `#56B4E9`, `#009E73`, `#F0E442`, `#0072B2`, `#D55E00`, `#CC79A7`) o Viridis para escalas continuas. El color nunca debe ser el único canal: añadir forma de marcador o etiqueta directa.
4. **Etiquetado directo sobre leyenda** siempre que quepa. La leyenda del mapa de estilos actual tapa puntos del propio scatter — es un problema real en la vista de equipos.
5. **Todo gráfico exportable en PNG con marca incrustada** (ver documento 04 y 02).
6. **Fondo oscuro consistente y un único color de acento.** Nada de que el acento cambie entre vistas.

---

## PRIORIDAD 1 — Radar comparativo de dos jugadores

**Pregunta que responde**: ¿en qué se parecen y en qué se diferencian dos jugadores de la misma posición?

**Por qué es lo primero**: la interfaz ya tiene el selector "Comparar con" y actualmente no produce nada visual. Es la funcionalidad más demandada en scouting y la que más rentabiliza el trabajo ya hecho.

**Implementación técnica**:
- `mplsoccer.PyPizza` soporta modo comparación nativo: se pasan `values` y `compare_values`, con `compare_colors` para diferenciar. Consultar la documentación de la versión instalada.
- Mantener el agrupado por familias (finalización / creación / construcción) ya existente.
- Los dos jugadores deben compartir grupo de comparación (misma posición o mismo rol). Si el usuario selecciona dos posiciones distintas, mostrar advertencia explícita: comparar un lateral con un delantero por el mismo vector de percentiles no tiene sentido futbolístico.

**Complemento recomendado — barras espejo (back-to-back)**:
El pizza comparado se satura visualmente con más de 8-10 métricas. Añadir como alternativa un gráfico de barras horizontales enfrentadas (jugador A a la izquierda del eje, jugador B a la derecha), ordenado por diferencia absoluta. Esto responde mejor a "¿dónde está la mayor diferencia entre ambos?", que es la pregunta real del scouting comparativo.

**Detalle numérico obligatorio debajo**: tabla con percentil y valor bruto de ambos jugadores, más minutos de cada uno.

---

## PRIORIDAD 2 — Rendimiento vs. valor de mercado

**Pregunta que responde**: ¿qué jugadores rinden por encima o por debajo de lo que dice su precio?

**Por qué**: es el análisis con mayor potencial de difusión en redes (identificar "gangas" e "inflados" genera conversación), y solo es posible porque ya tienes Transfermarkt integrado. Es tu diferencial frente a herramientas que solo miran rendimiento.

**Especificación**:
- Scatter: eje X = valor de mercado (escala logarítmica — los valores de mercado tienen distribución muy sesgada; en escala lineal el 90% de los puntos se apelmaza a la izquierda). Eje Y = un percentil compuesto de rendimiento (ver documento 03 para la definición del compuesto por rol).
- Línea de tendencia (regresión) que marque el "precio esperado" para cada nivel de rendimiento.
- Los puntos se colorean por su **residuo**: por encima de la línea = rinde más de lo que cuesta; por debajo = al revés.
- Filtros: posición, liga, edad, rango de valor.
- Etiquetar solo los outliers (los N residuos más extremos), no todos los puntos.

**Advertencia de lectura obligatoria** (esto es importante y debe aparecer en la interfaz): el valor de mercado no es solo rendimiento actual — incorpora edad, contrato restante, potencial, tamaño del club y nacionalidad. Un jugador "infravalorado" según este gráfico puede estarlo por razones legítimas. Presentarlo como detector de gangas sin este matiz sería exactamente el tipo de error que el resto de la plataforma evita.

---

## PRIORIDAD 3 — Distribución con posición del jugador (beeswarm / densidad)

**Pregunta que responde**: el percentil 85 de este jugador, ¿está pegado al pelotón o realmente descolgado del resto?

**Por qué es importante y poco común**: un percentil comprime información. Dos jugadores en el percentil 90 pueden tener valores brutos muy distintos si la distribución tiene cola larga. Mostrar la distribución completa con el jugador marcado es más honesto y es un gráfico que casi ninguna herramienta gratuita ofrece. Encaja perfectamente con la filosofía de "contexto para no leer mal el número".

**Especificación**:
- Para cada métrica del radar, un gráfico de densidad (KDE) o beeswarm de todos los jugadores de esa posición en Big 5.
- Marcador destacado en la posición del jugador seleccionado.
- Líneas verticales de referencia: mediana y percentiles 25/75.
- Presentación: en un desplegable "ver distribución" bajo el detalle numérico, o como vista secundaria en pestaña. No debe competir con el radar en la vista principal.

---

## PRIORIDAD 4 — Comparación 25/26 vs 26/27 (slope chart)

**Pregunta que responde**: ¿este jugador ha mejorado o empeorado respecto a la temporada pasada?

**Restricción metodológica crítica**: con dos temporadas NO se puede hablar de tendencia ni de evolución. Un gráfico de líneas con dos puntos sugiere una trayectoria que no existe en los datos. El formato correcto es un **slope chart** (dos columnas: 25/26 y 26/27, con líneas que conectan el valor de cada métrica), que representa honestamente un cambio entre dos observaciones, no una tendencia.

**Además**:
- 26/27 está en curso. Comparar una temporada completa con una parcial es incorrecto salvo que ambas estén normalizadas por 90 minutos (que lo están) y aun así hay que avisar del tamaño de muestra.
- Debe aparecer una advertencia explícita: "26/27 lleva X jornadas; los cambios de esta magnitud son esperables por azar en muestras de este tamaño". Idealmente acompañado de una banda de variación esperada (ver documento 03, sección de estabilización).

**Alternativa superior si se implementa el ingest de match logs** (ver documento 02): con datos por partido se puede hacer una media móvil intra-temporada, que sí es una tendencia legítima y mucho más informativa. Es la razón principal para priorizar esa integración.

---

## PRIORIDAD 5 — Heatmap de plantilla

**Pregunta que responde**: ¿dónde tiene fortalezas y agujeros la plantilla de este equipo?

**Especificación**:
- Matriz: jugadores en filas (agrupados por posición), métricas clave en columnas, color = percentil.
- Escala de color secuencial accesible (Viridis o similar), no divergente rojo-verde.
- Filas ordenables por minutos jugados o por percentil medio.
- Atenuar (opacidad reducida) las filas de jugadores por debajo del umbral de minutos, en lugar de excluirlos.

**Valor añadido**: es la vista más útil para la pestaña "Plantilla" que ya existe, y es muy vistosa para contenido en redes — un heatmap de plantilla de un club concreto es material de post directo.

---

## PRIORIDAD 6 — Trayectoria de valor de mercado

**Pregunta que responde**: ¿cómo ha evolucionado la valoración de este jugador a lo largo de su carrera?

**Por qué aquí sí hay serie temporal real**: el histórico de Transfermarkt tiene muchos más puntos que las dos temporadas de datos de rendimiento. Aquí un gráfico de líneas SÍ es apropiado.

**Especificación**:
- Línea temporal del valor de mercado del jugador.
- Marcadores sobre la línea en los momentos de traspaso (con club origen/destino e importe en el tooltip).
- Encaja en la pestaña "Mercado y carrera" ya existente.
- Opción de superponer un segundo jugador para comparar trayectorias de carrera.

---

## PRIORIDAD 7 — Ranking filtrable

**Pregunta que responde**: ¿quiénes son los mejores en X dentro de su posición?

**Especificación**:
- Barras horizontales ordenadas, top N configurable.
- Filtros: métrica, posición, liga, temporada, mínimo de minutos, rango de edad.
- Etiqueta con valor bruto y percentil.
- Enlace desde cada barra a la ficha del jugador.

**Por qué merece estar aquí pese a ser simple**: es la fábrica de contenido de la plataforma. Cada ranking es un post potencial, y es de lo más barato de implementar.

---

## Mejoras a gráficos existentes

### Pizza chart (vista de jugador)
- Añadir el número de jugadores de la población de comparación de forma visible (ya aparece "percentil frente a 415 jugadores" — mantenerlo, es correcto).
- Considerar ofrecer una vista alternativa en barras horizontales: con 8+ métricas el pizza es bonito pero menos legible que barras ordenadas. Ofrecer ambas y dejar elegir.
- Codificar visualmente la fiabilidad: si el jugador está por debajo del umbral de minutos, aplicar un patrón (rayado) o borde discontinuo a los sectores en lugar de solo avisar en texto.

### Mapa de estilos (vista de equipos)
- **Mover la leyenda fuera del área del gráfico**: actualmente tapa puntos. Usar etiquetado directo sobre los grupos o colocar la leyenda debajo.
- Añadir elipses o áreas sombreadas que delimiten cada cluster, reforzando visualmente la agrupación (ayuda mucho cuando el silhouette es bajo, porque muestra el solapamiento en vez de esconderlo).
- El eje Y (PPDA invertido) está bien resuelto con la etiqueta "arriba = más presión", pero conviene explicitar también que PPDA bajo = más presión en el propio tick del eje.
- La tabla inferior desborda a lo ancho: reducir columnas por defecto, con opción de expandir.

### Scatter de jugadores similares
- Está bien planteado. Añadir la posibilidad de fijar el jugador de referencia visualmente distinto (ya lo hace con el color morado) y permitir click sobre un punto para navegar a esa ficha.

---

## Resumen de orden de implementación

| # | Gráfico | Dependencias |
|---|---|---|
| 1 | Radar comparativo 2 jugadores | Ninguna (datos ya disponibles) |
| 2 | Rendimiento vs valor de mercado | Compuesto de rendimiento por rol (doc 03) |
| 3 | Distribución con posición del jugador | Ninguna |
| 4 | Slope chart 25/26 vs 26/27 | Ninguna |
| 5 | Heatmap de plantilla | Ninguna |
| 6 | Trayectoria de valor de mercado | Histórico Transfermarkt (ya disponible) |
| 7 | Ranking filtrable | Ninguna |
