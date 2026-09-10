# 03 · Profundidad analítica

Especificación de métricas, modelos y decisiones metodológicas.

> **Para Claude Code**: explora primero cómo se calculan los percentiles y el clustering actuales antes de modificar nada. Los cambios metodológicos aquí propuestos deben implementarse como funciones puras en `src/analysis/` (o el equivalente en la estructura existente), testeables con `pytest` sobre DataFrames sintéticos, sin dependencia de la base de datos.

---

## 1. El problema del tamaño de muestra (lo más importante de este documento)

La plataforma ya avisa textualmente de los minutos bajos. La mejora es pasar de avisar a **corregir**.

### El problema concreto
Un jugador con 135 minutos en el percentil 91 y uno con 2.500 minutos en el percentil 91 no son comparables. El primero es, en gran parte, ruido. La interfaz actual los muestra igual y delega la interpretación en el usuario.

### Solución: contracción bayesiana empírica (empirical Bayes shrinkage)

Para cada métrica, en lugar del valor observado se usa un valor contraído hacia la media de la población, con un peso proporcional a los minutos jugados:

```
valor_ajustado = w * valor_observado + (1 - w) * media_poblacion
donde w = minutos / (minutos + k)
```

`k` es una constante de estabilización específica de cada métrica: cuántos minutos hacen falta para que esa métrica sea informativa. Se estima empíricamente (correlación partida en dos mitades de la temporada) o se fija con criterio.

### Órdenes de magnitud de estabilización (criterio futbolístico)

Las métricas no estabilizan al mismo ritmo. Aproximadamente, de más rápida a más lenta:

| Métrica | Estabilización | Razón |
|---|---|---|
| Tiros por 90, toques, pases intentados | Rápida | Alto volumen de eventos por partido |
| npxG por 90, xA por 90 | Media | Volumen moderado, pero acumulativo |
| Pases progresivos, acciones defensivas | Media | Depende mucho del estilo del equipo |
| % de conversión, goles − xG | Muy lenta | Eventos raros; casi todo es varianza en menos de una temporada completa |
| Paradas evitadas (porteros) | Muy lenta | Los porteros necesitan varias temporadas |

**Consecuencia para la interfaz**: métricas de finalización con muestra pequeña deberían mostrarse con una advertencia mucho más fuerte que métricas de volumen. Esto ya lo insinúa el texto de la home ("describe una racha, no una habilidad") — el paso siguiente es sistematizarlo.

### Implementación recomendada
- Calcular ambos valores: percentil observado y percentil ajustado.
- Mostrar el observado por defecto (es lo que el usuario espera) pero con un indicador visual de fiabilidad.
- Ofrecer un conmutador "ajustar por tamaño de muestra" que aplique la contracción.
- Documentar la constante `k` usada por métrica en la sección de metodología.

---

## 2. Ajuste por posesión (possession-adjusted)

**El problema**: las métricas defensivas por 90 minutos penalizan sistemáticamente a los jugadores de equipos dominantes. Un centrocampista del Manchester City hace menos entradas por 90 no porque defienda peor, sino porque su equipo tiene el balón el 65% del tiempo y hay menos ocasiones de defender.

**La corrección**: normalizar las acciones defensivas por el tiempo sin balón, no por el tiempo total.

```
accion_padj = accion_por_90 * (50 / porcentaje_posesion_sin_balon_del_equipo)
```

La interfaz ya tiene un conmutador "Ajustado por posesión" — verificar qué aplica exactamente y a qué métricas. **Debe aplicarse solo a métricas defensivas y de recuperación**, no a métricas ofensivas (donde el ajuste correcto sería el inverso: normalizar por posesión con balón).

**Simétricamente**, métricas ofensivas pueden ajustarse por posesión con balón, lo que corrige el sesgo contrario: un extremo de un equipo que apenas tiene el balón parece peor de lo que es.

---

## 3. Compuestos por rol (necesario para el gráfico de valor de mercado)

Para el scatter rendimiento-vs-valor hace falta un único número de rendimiento por jugador. No puede ser el mismo para todas las posiciones.

**Enfoque recomendado**: media ponderada de percentiles, con pesos definidos por rol.

Ejemplo de estructura (los pesos concretos son una decisión futbolística que debe documentarse y justificarse):

- **Delantero centro**: npxG (peso alto), xA, tiros, toques en área, npxG por tiro.
- **Extremo**: npxG+xA, regates completados, pases progresivos recibidos, centros.
- **Mediocentro organizador**: pases progresivos, xGBuildup, % de pase bajo presión, pases al último tercio.
- **Mediocentro destructor**: acciones defensivas padj, intercepciones, duelos ganados, recuperaciones en campo rival.
- **Lateral**: pases progresivos, centros, xA, acciones defensivas padj, duelos 1v1.
- **Central**: duelos aéreos, acciones defensivas padj, % de pase, pases progresivos, errores que derivan en tiro (peso negativo).
- **Portero**: goles evitados sobre esperados, % de pases largos completados, salidas.

**Regla de honestidad**: cualquier compuesto es una opinión disfrazada de número. La interfaz debe permitir ver los pesos usados y, si es posible, ajustarlos. Un compuesto opaco es exactamente lo contrario a la filosofía del resto de la plataforma.

---

## 4. Clustering de roles de jugador

Actualmente hay clustering de estilos de equipo. El equivalente a nivel de jugador está pendiente y es muy valioso: agrupar jugadores por **cómo juegan**, no por la posición nominal que les asigna FBref.

**Por qué importa futbolísticamente**: la etiqueta "MF" agrupa a un pivote posicional, un box-to-box y un mediapunta. Son tres jugadores incomparables entre sí. El clustering por vector de métricas descubre los roles reales que existen en los datos.

**Implementación**:
- Clustering sobre el vector de percentiles dentro de cada macro-posición (no mezclar defensas con delanteros).
- K-means o clustering jerárquico. Evaluar con silhouette, pero — igual que con los equipos — asumir que los roles son un continuo y comunicarlo con la misma honestidad que ya se hace en la vista de equipos.
- Nombrar cada cluster por sus rasgos extremos, no con etiquetas genéricas. La vista de equipos ya lo hace bien ("cada llegada es peligrosa, poca presencia en campo rival"); replicar ese criterio.

**Uso en la interfaz**: la opción "comparar contra su rol (más fino, muestra menor)" ya existe en los filtros. El clustering de roles es lo que la haría verdaderamente potente, y hay que explicitar el trade-off: comparación más relevante, pero población más pequeña y por tanto percentiles menos estables.

---

## 5. Similitud entre jugadores

Ya está implementado. Refinamientos posibles:

- **Métrica de distancia**: verificar si se usa distancia euclídea o similitud coseno sobre el vector de percentiles. La similitud coseno captura mejor "el mismo perfil a distinto nivel" (dos jugadores con la misma forma de radar pero uno mejor en todo), mientras que la euclídea penaliza esa diferencia de nivel. Ambas responden preguntas distintas: "¿quién juega parecido?" vs "¿quién es un sustituto directo?". Idealmente, ofrecer las dos.
- **Ponderación por relevancia**: no todas las métricas deberían pesar igual en la similitud. Un delantero que coincide en npxG es más "similar" que uno que coincide en pases totales.
- **Filtros de utilidad práctica**: poder restringir los similares por edad, valor de mercado y contrato convierte la herramienta de "curiosidad" en "scouting real". Esta es la funcionalidad que más se acerca a lo que hace un departamento de scouting.

La nota al pie actual ("el parecido solo abarca lo que mide el catálogo... dos defensas parecidos lo son con balón, no defendiendo") es exactamente el tipo de honestidad que hay que mantener. Debe seguir visible.

---

## 6. Métricas a añadir al catálogo

Ordenadas por valor añadido:

| Métrica | Qué aporta | Fuente |
|---|---|---|
| npxG por tiro | Calidad media de ocasión; separa al que genera buenas ocasiones del que dispara mucho | Understat / FBref |
| Pases progresivos recibidos | Clave para extremos y delanteros: mide capacidad de aparecer en zonas de peligro | FBref |
| Acciones defensivas en campo rival | Marcador de presión alta a nivel individual | FBref |
| Duelos aéreos ganados (%) y volumen | Esencial para centrales y delanteros de referencia | FBref |
| Conducciones progresivas | Distingue al que progresa con el balón del que progresa pasando | FBref |
| Errores que derivan en tiro | De las pocas métricas negativas útiles; importante en centrales | FBref |
| % de pases completados bajo presión | Solo si hay datos de presión disponibles | Limitado en FBref |
| Goles evitados sobre esperados (PSxG−GA) | La métrica de portero por excelencia | FBref |

**Nota sobre porteros**: la plataforma debería tener un catálogo de métricas específico para porteros y una advertencia especialmente fuerte sobre tamaño de muestra (las métricas de portero necesitan varias temporadas para ser informativas).

---

## 7. Estilo de equipo: métricas adicionales

El mapa actual usa llegadas a zona de remate y PPDA. Ampliaciones que enriquecerían el clustering:

- **Field tilt**: porcentaje de la posesión en el último tercio propio frente al del rival. Mide territorialidad mejor que la posesión bruta.
- **Directness / verticalidad**: distancia progresada por pase, o ratio de progresión vertical sobre pases totales.
- **Altura de la línea defensiva** (aproximable por la distancia media de las acciones defensivas al propio arco).
- **Dependencia de balón parado**: porcentaje de xG generado desde acciones a balón parado. Diferencia mucho estilos.
- **xG concedido por tiro**: mide si el equipo concede muchas ocasiones o pocas pero buenas.

**Sobre el silhouette de 0.16**: el aviso actual es correcto y honesto. Añadir métricas más discriminantes (como field tilt y directness) probablemente mejore la separación, porque las dos variables actuales están correlacionadas entre sí. Merece la pena probarlo y reportar el cambio en el silhouette.

---

## 8. Trampas metodológicas a evitar (checklist)

Este es el criterio que hay que mantener en cada análisis nuevo:

1. **No presentar diferencias dentro del rango de ruido como si fueran señal.** Especialmente en goles vs xG.
2. **No comparar entre posiciones distintas** sin advertirlo explícitamente.
3. **No inferir causalidad** de correlaciones (un equipo no gana porque presione; puede presionar porque va ganando).
4. **No ignorar el efecto del equipo**: las métricas individuales están fuertemente condicionadas por el estilo colectivo. Un pivote de un equipo que no tiene el balón nunca tendrá buenos números de progresión.
5. **No tratar el valor de mercado como medida de calidad**: incorpora edad, contrato, marca y club.
6. **No extrapolar de una temporada parcial** sin ajustar por muestra.
7. **No ocultar la incertidumbre para que el gráfico quede más limpio.** La plataforma ya hace lo contrario y ese es su mayor activo.
