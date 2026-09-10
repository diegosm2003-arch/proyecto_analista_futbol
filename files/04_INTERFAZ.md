# 04 · Interfaz y experiencia de uso

Especificación de mejoras de interfaz, arquitectura de información y coherencia visual.

> **Para Claude Code**: explora cómo está estructurada la aplicación de Streamlit antes de reorganizar nada. Estas mejoras son incrementales; no reescribas la aplicación.

---

## 1. Reorganización de la vista de jugador (prioridad máxima)

**Problema actual**: el contenido se apelmaza contra el margen izquierdo dejando una franja vacía a la derecha. El radar y el panel de lectura compiten por la atención en la parte superior. Los jugadores similares quedan enterrados muy abajo.

**Layout propuesto** (dos columnas):

```
┌─────────────────────────────────────────────────┐
│ Filtros: temporada · posición · jugador · comparar │
├──────────────────────┬──────────────────────────┤
│                      │ Titular + lectura         │
│      RADAR           ├──────────────────────────┤
│      (pizza)         │ Advertencias de lectura   │
│                      ├──────────────────────────┤
│                      │ Detalle numérico          │
├──────────────────────┴──────────────────────────┤
│  Jugadores similares    │    Scatter comparativo  │
└─────────────────────────────────────────────────┘
```

- Columna izquierda fija: el radar.
- Columna derecha, apilados: titular interpretado, advertencias, detalle numérico.
- Ancho completo debajo: similares y scatter, lado a lado.

En Streamlit esto se resuelve con `st.columns([1, 1])` para el bloque superior y otro `st.columns` para el inferior.

**Jerarquía de lectura resultante**: primero el perfil visual, luego su interpretación, luego los comparables. Es el orden natural en que un analista lee una ficha.

---

## 2. Coherencia de sistema visual

### Color
- **Un único color de acento en toda la plataforma.** Actualmente el icono de marca es dorado en la home y morado en las vistas internas. Elegir uno (recomendación: dorado, es más distintivo sobre fondo oscuro y transmite producto premium) y aplicarlo consistentemente.
- Paleta completa: fondo oscuro + un acento + una escala de grises para texto. Nada más en la interfaz. Los colores categóricos se reservan para los datos dentro de los gráficos.
- **Paleta de datos accesible para daltonismo** (ver documento 01).

### Componente de insight reutilizable
La home tiene un patrón excelente: `ETIQUETA → titular → dato → "Ojo: ..."`. Ese patrón debe convertirse en un componente reutilizable que aparezca idéntico en:
- La home (ya está).
- La vista de jugador (el panel "dónde se sale de lo normal" ya se le parece — unificarlo).
- La vista de equipo.

Un patrón visual repetido es lo que convierte varias pantallas en un producto.

### Tipografía
La tipografía condensada de los titulares tiene carácter y funciona. Mantenerla como seña de identidad, con una única tipografía de apoyo para el cuerpo.

---

## 3. Corrección ortográfica (barato, alto impacto)

Los textos mezclan acentuación correcta con palabras sin tildar: "posicion", "presion", "construccion", "creacion", "penaltis" (correcto), "Analizar", "Futbol". Para una pieza de portfolio dirigida al mercado español, esto resta credibilidad de forma desproporcionada a lo trivial que es corregirlo.

**Acción**: revisar todos los strings de la interfaz de una pasada. Incluye títulos de ejes de gráficos, etiquetas de clusters y textos de ayuda.

---

## 4. Rendimiento percibido

- **Cacheo**: aplicar `@st.cache_data` a los cálculos de percentiles, clustering y consultas a la API. Sin esto, Streamlit recalcula en cada interacción con cualquier filtro y la experiencia se degrada mucho.
- **Cacheo con TTL** para las llamadas a la API, de forma que los datos se refresquen cuando el ETL actualiza pero no en cada clic.
- **Estados de carga explícitos** (`st.spinner`) en las operaciones lentas: clustering, cálculo de similares, carga de plantillas.

---

## 5. Transparencia metodológica

Coherente con la filosofía de la plataforma, debe haber una vía para responder "¿cómo se calcula esto?":

- Icono de información junto a cada métrica del radar, con definición breve y fuente.
- Página o sección de metodología: cómo se calculan los percentiles, cuál es la población de referencia, qué significa el ajuste por posesión, cómo se forman los clusters, qué umbral de minutos se aplica y por qué.
- **Fecha de actualización de los datos visible de forma permanente**: "datos hasta la jornada X de la temporada 26/27". Es información de contexto imprescindible y genera confianza.

---

## 6. Primera impresión

- **Frase de posicionamiento rotunda en la home.** El subtítulo actual ("Cada número viene con el contexto que hace falta para no leerlo mal") es muy bueno — de hecho es el mejor activo de marca del proyecto. Considerar elevarlo a lema principal.
- **Estado inicial de las vistas internas**: qué se ve antes de seleccionar un jugador. Un estado vacío bien resuelto (por ejemplo, sugerencias de jugadores destacados de la jornada) invita a explorar mejor que un formulario vacío.

---

## 7. Navegación

- **Breadcrumb consistente**: la vista de equipos ya tiene "Todas las ligas → Premier League". Aplicarlo en todas las vistas internas.
- **Click sobre un jugador en cualquier gráfico debería llevar a su ficha** (similares, ranking, heatmap de plantilla). Es la interacción que más fluidez añade.
- **Persistencia de filtros** al navegar entre pestañas: si el usuario está mirando 26/27 y cambia de pestaña, no debería resetearse.

---

## 8. Responsividad y accesibilidad

- Comprobar el comportamiento en pantalla de portátil (13-14") y en móvil. Las capturas actuales son de pantalla muy ancha; el layout de dos columnas debe degradar a una columna en pantallas estrechas (`st.columns` no lo hace automáticamente en todos los casos — verificar).
- **Contraste de texto**: revisar los grises sobre fondo oscuro; algunos textos secundarios pueden quedar por debajo del mínimo legible.
- **No depender solo del color** para transmitir información en los gráficos (ver documento 01).

---

## 9. Detalles de presentación para portfolio

- **Ocultar el botón "Deploy"** de Streamlit en las capturas y demostraciones (menú de configuración de la app, o recortar).
- **README con narrativa**: capturas, GIF de la app en uso, arquitectura explicada, decisiones de diseño justificadas. Es donde un reclutador técnico pasa más tiempo, y suele estar descuidado en la mayoría de portfolios.
- **Nombre y marca**: "Futbol Analytics" es descriptivo pero genérico. Alternativas con más carácter: **Percentil**, **Contexto FC**, **Regista**. La decisión debe tomarse antes de aplicar la coherencia visual, para no hacer el trabajo dos veces.

---

## Orden de implementación sugerido

| # | Mejora | Esfuerzo | Impacto |
|---|---|---|---|
| 1 | Corrección ortográfica | Muy bajo | Alto (credibilidad) |
| 2 | Color de acento único | Bajo | Alto (coherencia) |
| 3 | Cacheo y estados de carga | Bajo | Alto (uso diario) |
| 4 | Reorganización vista de jugador | Medio | Muy alto |
| 5 | Fecha de datos + metodología | Bajo | Alto (confianza) |
| 6 | Componente de insight unificado | Medio | Alto (identidad) |
| 7 | Navegación por click y breadcrumbs | Medio | Medio |
| 8 | Responsividad y accesibilidad | Medio | Medio |
