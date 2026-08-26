# Navegación parental (Inicio + Archivos) — diseño

Fecha: 2026-08-25  
Producto: app Android MiCompañero (padres, primera infancia)  
Estado: aprobado en conversación; pendiente de plan de implementación

## Problema

La app tiene **tres caminos** (barra inferior, overflow ⋮, drawer). En el teléfono, Cuentos, Agenda médica y Configuración están en ⋮. Las canciones viven en Configuración, no junto a los cuentos. Celebrar está dos veces (tarjeta + FAB). Un padre con un nene en brazos no encuentra lo cotidiano.

La skill de UI (Tailwind/React) se traduce a **Material en Android**: jerarquía, estados, a11y y pulido. No se usa Tailwind, Framer ni estética SaaS oscura. Se mantiene la paleta actual (lavanda, coral, fondos claros).

## Objetivo de esta iteración

Hacer la app **fácil de navegar y de aprender**: cuatro pestañas visibles, configuración en el engranaje, música rápida en Inicio, biblioteca (cuentos + canciones) en **Archivos**.

Criterio de éxito: sin leer un tutorial, un padre llega a Inicio (estado + play/stop + celebrar), Rutinas, Archivos y Agenda; Configuración está en el engranaje; Métricas se abre desde “Ver detalle”.

## Fuera de alcance (esta iteración)

- Rediseño visual de Rutinas, Agenda, Métricas y Config (más allá de quitar canciones de Config).
- Dark mode nuevo, glassmorphism, sombras premium.
- APIs nuevas en la Pi.
- Pantalla propia de Música.
- Quinto ítem en la barra.
- Reescribir copy de Métricas (futuro).
- Borrar todos los layouts `layout-w600dp` / `layout-w1240dp` de plantilla (futuro: si no aportan, se sacan).

## Arquitectura de navegación

Barra inferior, orden fijo, ícono **y** etiqueta:

| Posición | Destino | Destino de nav |
|---|---|---|
| 1 | Inicio | `nav_dashboard` |
| 2 | Rutinas | `nav_routines` |
| 3 | Archivos | `nav_stories` (mismo fragmento, label nuevo) |
| 4 | Agenda | `nav_medical` |

Toolbar, todas las pestañas: ícono engranaje → `nav_config`. `contentDescription`: “Configuración”.

**Métricas** (`nav_metrics`): no está en la barra. Se abre desde Inicio → **Ver detalle**. Atrás vuelve a Inicio.

**Se elimina en teléfono:**

- Overflow ⋮ con Cuentos / Agenda / Config.
- Drawer hamburguesa (duplicaba destinos).

**Tablet:** misma barra de 4 + engranaje. No hay un segundo menú distinto.

`AppBarConfiguration` top-level: `nav_dashboard`, `nav_routines`, `nav_stories`, `nav_medical`. Config y Métricas no son top-level (muestran flecha atrás).

## Inicio

Una columna, este orden:

1. **Peluche** — card de conexión + botón de encendido actuales.
2. **Música ahora** — card nueva: título de la canción en curso o “Nada sonando”; botones **Play** y **Stop**; **sin lista**.
   - Play: retoma la última canción reproducida (`currentlyPlaying` / última pedida). Si nunca se eligió una, reproduce la **primera** de `/api/music`.
   - Sin canciones en el peluche: Play **disabled**; texto “Cargá una en Archivos”.
   - Stop: `POST /api/music/stop` (igual que hoy).
3. **Hoy** — tres cifras actuales (interacciones, juego, ánimo) + enlace **Ver detalle** → `nav_metrics`.
4. **Celebrar** — solo la card clickeable. **Se oculta / se quita el FAB.**
5. **Alertas** — lista corta o “No hay alertas nuevas”.

El FAB de `app_bar_main` no se muestra en ningún destino.

## Archivos

Misma pantalla (`StoriesFragment` + layout), dos bloques verticales **sin** chips ni pestañas internas:

1. **Cuentos** — lista, subir PDF, borrar (comportamiento actual). Título de sección: “Lo que TEO puede leer”. Vacío: “Todavía no hay cuentos”.
2. **Canciones** — lista, play, stop, subir, borrar (lógica actual de `ConfigFragment` / `ConfigViewModel`, movida aquí). Título: “Lo que TEO puede poner”. Vacío: “Todavía no hay canciones”.

Play en Archivos **elige** la canción (queda como última para Inicio). Inicio solo retoma o para.

Label de menú: **Archivos**. Ícono: carpeta (`ic_stories_24dp` se retinta o se reemplaza por un vector de carpeta en `drawable/`; un solo ícono, no un pack).

## Configuración

Se quita el bloque de canciones (título, lista, parar, subir). Quedan sensorial, volumen, Wi‑Fi / vínculo y “Acerca de”.

## Datos

Sin endpoints nuevos. Reutilizar:

- `GET/POST /api/music`, play, stop, upload, delete
- `GET/POST/DELETE /api/stories` (como hoy)

`RobotConnectionManager` sigue siendo la fachada. El estado “canción actual” se comparte entre Inicio y Archivos (mismo manager / mismo poll que ya usa Config).

## Errores

- Peluche no configurado o offline: Play/Stop y subidas → snackbar “¿Está conectado el peluche?”; chip Desconectado en Inicio.
- Play sin canciones: no llama a la API; botón disabled + hint a Archivos.
- Fallo de subida: snackbar con motivo; la lista previa se mantiene.
- Métricas vacías: Inicio “Sin datos”; Ver detalle abre la pantalla actual.

## Accesibilidad

- Bottom nav: siempre `app:labelVisibilityMode="labeled"`.
- Engranaje, Play, Stop, Celebrar: `contentDescription` en español; min 48 dp.
- Estados enabled/disabled visibles (no solo color de ícono).
- Transición entre pestañas: default de Navigation / Material. Sin librerías de motion nuevas.

## Pruebas (manual; no hay suite UI)

- Barra: Inicio, Rutinas, Archivos, Agenda. No aparece Métricas ni Config como ítem inferior.
- Engranaje abre Config; atrás vuelve a la pestaña de origen.
- ⋮ no lista Cuentos/Agenda/Config.
- Inicio: play/stop sin lista; no hay FAB.
- Archivos: cuentos + canciones; Config sin música.
- Ver detalle → Métricas → atrás = Inicio.
- Play en Inicio con biblioteca vacía: disabled + hint.

## Futuro (documentado, no implementar)

1. Look unificado de Rutinas, Agenda, Métricas y Config (cards, tipografía, espacios).
2. Fases 2–4 de la skill en Android: estados press, dark mode coherente, sombras.
3. Limpiar layouts de plantilla tablet (`transform`, drawer `w600dp`) si no se usan.
4. Copy parental en Métricas (menos jerga de “desarrollo cognitivo”).
5. Animaciones de entrada más ricas.
6. Si la biblioteca crece: chips Cuentos | Canciones **dentro** de Archivos (hoy no).

## Archivos de código previstos (orientativo)

Modificar: `bottom_navigation.xml`, `overflow.xml`, `navigation_drawer.xml`, `MainActivity.kt`, `app_bar_main.xml`, `fragment_dashboard.xml` + `DashboardFragment` / `DashboardViewModel`, `fragment_stories.xml` + `StoriesFragment` / `StoriesViewModel`, `fragment_config.xml` + `ConfigFragment` / `ConfigViewModel`, `strings.xml`.

No modificar el servidor de la Pi salvo bugs descubiertos al cablear la misma API.
