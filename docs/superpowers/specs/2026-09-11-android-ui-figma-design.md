# MiCompañero Android → Figma

Fecha: 2026-09-11  
Producto: app parental Android MiCompañero (peluche TEO)  
Estado: aprobado en conversación; pendiente de plan de implementación  
Fuente de verdad: layouts y temas en `ProyectoAndroid/app/src/main/res/`

## Objetivo

Traspasar el UI **actual** de la app Android a un archivo Figma nuevo, para que quede como fuente de verdad visual (no un rediseño).

El archivo usa un **sistema de diseño local**: variables con modos Light y Dark, componentes ligados a esas variables, y pantallas como instancias. Oscuro no se pinta a mano.

Criterio de éxito: un padre que conoce la app reconoce cada pantalla; un cambio de `color/primary` actualiza Light y Dark.

## Fuera de alcance

- Layouts tablet (`layout-w600dp`, `layout-w1240dp`) y el drawer que solo existe ahí (`nav_view`).
- Rediseño, glassmorphism, sombras “premium”, animaciones, ripple Material exacto.
- Banner de debug de Config.
- Un frame por cada período de métricas (Hoy / Semana / Mes es variante del selector, no pantallas distintas).
- Inicio “Desconectado” como pantalla aparte (el chip es variante del componente).
- Notificaciones de sistema, teclado, splash, launcher.
- Code Connect, librería de equipo, publicación de library.
- Commit git (hasta que Teo lo pida).

## Corrección respecto al inventario hablado

En teléfono **no hay drawer**. `activity_main.xml` (default) no infla `NavigationView`. La navegación real es:

| Control | Destinos |
|---|---|
| Barra inferior (4 ítems, ícono + etiqueta) | Inicio, Rutinas, Archivos, Agenda Médica |
| Engranaje del toolbar | Configuración |
| Inicio → “Ver detalle” | Cómo estuvo (`nav_metrics`) |

El frame “Inicio + drawer abierto” **no se construye**. El chrome de teléfono es status bar + AppBar + contenido + barra inferior.

Configuración y Cómo estuvo no son top-level: AppBar con flecha atrás. La barra inferior sigue visible (está en `content_main.xml`); ningún ítem queda seleccionado.

## Archivo Figma

- Nombre: **MiCompañero — Android UI**
- Creación: `create_new_file` (drafts del plan de Figma de Teo)
- Frames de pantalla: **360 × 800** (dp Android)

Páginas:

1. **Foundations** — variables, text styles, effect styles
2. **Components** — primitivos reutilizables
3. **Screens / Light** — destinos con modo Light
4. **Screens / Dark** — mismos destinos, modo Dark aplicado (no redibujar)

## Tokens

Colección `MiCompañero`, modos `Light` y `Dark`. Scopes explícitos (fill, text, gap, radius). No `ALL_SCOPES`.

Hex sin el canal alpha `FF` de Android; opacidad aparte cuando aplique.

### Color — primitivos (iguales en ambos modos salvo nota)

| Token | Light | Dark | Uso |
|---|---|---|---|
| `color/primary` | `#6750A4` | `#7E6BC4` (`primary_light`) | AppBar, botones filled, métricas |
| `color/primary-dark` | `#4F378B` | `#4F378B` | Status bar en Light |
| `color/on-primary` | `#FFFFFF` | `#000000` | Texto/íconos sobre primary |
| `color/secondary` | `#EF8A7E` | `#FFB4AB` | Acento coral |
| `color/secondary-dark` | `#D4574E` | `#EF8A7E` | Título celebrar |
| `color/tertiary` | `#4ECDC4` | `#4ECDC4` | Botón buscar / aplicar |
| `color/background` | `#F8F5FC` | `#1C1B1F` | Fondo de pantalla |
| `color/surface` | `#FFFFFF` | `#2B2930` | Cards blancas, barra inferior |
| `color/on-background` | `#1C1B1F` | `#E6E1E5` | Títulos de sección |
| `color/on-surface` | `#1C1B1F` | `#E6E1E5` | Texto de card |
| `color/text-hint` | `#9E9E9E` | `#9E9E9E` | Subtítulos |
| `color/divider` | negro 12% | blanco 12% | Separadores |
| `color/status-online` | `#4CAF50` | igual | Chip conectado |
| `color/status-offline` | `#BDBDBD` | igual | Chip desconectado |
| `color/celebrate` | `#FFAB40` | igual | Ícono celebrar |
| `color/card-lavender` | `#F3E5F5` | **igual** | Card colored |
| `color/card-peach` | `#FFF3E0` | **igual** | Card colored |
| `color/card-mint` | `#E0F2F1` | **igual** | Card colored |
| `color/card-sky` | `#E3F2FD` | **igual** | Card colored |
| `color/card-rose` | `#FCE4EC` | **igual** | Card colored |

Los pasteles **no** tienen `values-night`. En Dark las cards de color siguen siendo esas pasteles sobre `#1C1B1F`. No inventar pasteles oscuros.

Status bar: Light = `primary-dark`; Dark = `background`.

### Spacing y radius (número, ambos modos)

| Token | Valor | Origen |
|---|---|---|
| `space/4` | 4 | márgenes entre tiles |
| `space/8` | 8 | gaps internos |
| `space/12` | 12 | icono→texto |
| `space/16` | 16 | padding de pantalla y card |
| `space/24` | 24 | `section_margin_top` |
| `radius/8` | 8 | outlined en Archivos / conectar |
| `radius/12` | 12 | botones filled Inicio |
| `radius/16` | 16 | `Widget.App.CardView` |
| `radius/20` | 20 | `Widget.App.CardView.Colored` |

### Tipografía

Fuente **Roboto**. Si Figma no la tiene cargada, **Inter** con los mismos tamaños (no mezclar las dos en un mismo archivo).

| Style | Size | Weight | Color |
|---|---|---|---|
| Section Title | 18 | Bold | `on-background` |
| Card Title | 16 | Bold | `on-surface` |
| Card Subtitle | 13 | Regular | `text-hint` |
| Metric Value | 28 | Bold | `primary` |
| Body | 15–16 | Regular | `on-surface` |
| AppBar Title | 20 | Medium | `on-primary` |
| Bottom Nav Label | 12 | Medium | `primary` / hint |

### Efectos

- `elevation/card`: sombra suave equivalente a elevation 2 dp (solo `Widget.App.CardView`).
- Cards colored: **sin** sombra (elevation 0).

## Componentes (página Components)

Construir en este archivo (no hay Code Connect ni library). Fills, padding, radius y texto ligados a variables. Iconos: SVG de `res/drawable`, no emoji improvisado ni líneas rotadas.

| Componente | Variantes / notas |
|---|---|
| StatusBar | Light / Dark (hora 15:46, iconos sistema simples) |
| AppBar | Top-level (solo título + engranaje) vs subpantalla (flecha atrás + título + engranaje) |
| BottomNav | 4 ítems; `Selected` en uno o en ninguno |
| Card | Default (surface + elevation + radius 16) / Colored (pastel + radius 20, sin sombra) |
| Button | Filled (primary o tertiary) / Outlined / Text; min height 48 |
| ChipStatus | Conectado / Desconectado |
| FAB | primary, ícono add, 56 |
| ListRow | rutina / cuento / canción / turno / vacuna |
| TextField | outlined, counter 80 en nombre de cuento |
| Switch | off (Config modo noche) |
| Slider | track primary / happy / tertiary según Config |
| MetricTile | sky / mint / peach / rose / lavender |
| PeriodSelector | Hoy seleccionado |
| Dialog | contenedor modal + scrim |

## Inventario de frames

Cada destino se construye **una vez** en Light y se duplica a Dark cambiando el modo de la colección. No hay 20 combinaciones.

Shell compartido (salvo nota): StatusBar + AppBar + contenido scroll + BottomNav.

| Frame | AppBar | BottomNav seleccionado | Contenido |
|---|---|---|---|
| Inicio | Inicio + engranaje | Inicio | ver sección Inicio |
| Cómo estuvo | atrás + Cómo estuvo + engranaje | ninguno | período Hoy; ver Métricas |
| Rutinas | Rutinas + engranaje | Rutinas | 3 filas + FAB |
| Rutinas vacía | igual | Rutinas | copy `routines_empty` + FAB |
| Archivos | Archivos + engranaje | Archivos | cuentos + canciones con ítems |
| Archivos vacío | igual | Archivos | `stories_empty` + `files_songs_empty` + botones subir |
| Agenda médica | Agenda Médica + engranaje | Agenda | 1 turno, 4 vacunas, recordatorios |
| Configuración | atrás + Configuración + engranaje | ninguno | ver sección Config |

Overlays (solo Light y Dark sobre Archivos, no frames de destino extra):

- **Nombre del cuento** — `dialog_story_name.xml`: campo + counter 80, Aceptar / Cancelar
- **Editar cuento** — `dialog_story_edit.xml`: título + texto multilínea, Guardar / Cancelar

FAB de Rutinas: `bottom|end`, margen 16, **por encima** de la barra inferior (el Recycler ya reserva `paddingBottom` 72).

## Contenido de cada pantalla (Light = Dark en copy)

Copy de `strings.xml`. Donde el XML de layout tiene texto hardcodeado (Config: “Buscar automáticamente”, “Conectar manualmente”, “Aplicar cambios”, IP), se copia tal cual, incluidos los emoji que ya están en el layout.

### Inicio (`fragment_dashboard.xml`)

Orden vertical, padding 16:

1. Card colored lavender: ícono teddy, “Estado del Peluche”, “Vinculación vía Wi-Fi”, chip **Conectado**.
2. Botón filled primary: “Encendido” + ícono teddy.
3. Título “Ahora”. Card colored mint: “Nada sonando”; Play (filled) + Stop (outlined).
4. Título “Resumen del Día”. Tres MetricTiles: **12** Interacciones (sky), **45 min** Tiempo de juego (mint), **Tranquilo 😊** Estado emocional (peach, metric a 16 sp porque el texto no cabe a 28).
5. Text button alineado a la derecha: “Ver detalle”.
6. Card colored rose clickeable: ícono celebrate, “¡Celebrar Logro!”, subtítulo de `dashboard_celebrate_subtitle`.
7. Título “Alertas Recientes”. Card default: “No hay alertas nuevas”.

### Cómo estuvo (`fragment_metrics.xml`)

1. PeriodSelector: tres TextButton (Hoy / Semana / Mes). Hoy usa color `primary`; los otros, `text-hint`.
2. Tres tiles: interacciones **12**, juego **45 min**, avisos **0**.
3. Dos tiles: Juegos **3**, Rutinas **2**.
4. “En qué anduvo”: card con donut 200×200 (cuatro arcos: alert `#FF8A65`, tertiary, primary_light, happy `#FFCA28`) + leyenda (Cómo se sintió / Juego y charla / Con vos / Haciendo solo).
5. “Veces que hablaron”: card con barras 200 de alto, 7 días de ejemplo (no el string “Gráfico disponible próximamente”: el layout usa `WeekBarChart`).
6. “Palabras”: card mint, “8 palabras conocidas” / “3 esta semana”.

### Rutinas

Título “Rutinas del Día”. Filas (strings de sample):

- Desayuno · 08:00
- Siesta · 14:00
- Hora de dormir · 20:30

Vacío: “No hay rutinas configuradas.\nTocá + para agregar una.”

### Archivos

1. “Lo que TEO puede leer” + `stories_subtitle`. Card: dos filas de cuento (El patito y la luna, Los tres amigos) + “Subir PDF” outlined.
2. “Lo que TEO puede poner”. Card: dos filas de canción (Estrellita, El baile del oso) + “Parar canción” + “Subir canción” outlined.

Vacío: “Todavía no hay cuentos” / “Todavía no hay canciones” + los mismos botones.

Diálogo nombre: hint “Nombre del cuento”, counter 80, Aceptar / Cancelar.  
Diálogo editar: título “El patito y la luna”, 3–4 líneas de texto infantil, Guardar / Cancelar.

### Agenda médica

- “Turnos Médicos” + text button “Agregar Turno”. Un turno: Control pediátrico · 15 de julio, 10:00.
- “Calendario de Vacunación” + hint `medical_vaccines_hint`. Card: BCG Al nacer ✓, Hepatitis B Al nacer ✓, Neumococo 2 meses ✓, Quíntuple 4 meses - Pendiente.
- Card mint: Recordatorios + `medical_reminder_subtitle`.

### Configuración (`fragment_config.xml` actual)

Sin banner debug. Sin catálogo de canciones (se movió a Archivos).

1. “Conexión”: estado “Desconectado” (copy del layout), botón tertiary “Buscar automáticamente”, hint IP, TextField “IP del Robot (ej. 192.168.1.100)” con `192.168.0.136`, outlined “Conectar manualmente”.
2. “Configuración Sensorial”: sliders Volumen 100%, Brillo 100%, Límite de tiempo “Sin límite” (valor 0); “Aplicar cambios” tertiary.
3. Card sky: Modo Noche + switch off + subtítulo TEO.
4. Card lavender: Acerca de · Versión 1.0.0.

## Fidelidad

Documentar, no inventar.

**1:1:** estructura XML, strings, hex, radios, padding 16, minHeight 48, iconos drawable, pasteles fijos en Dark.

**Simplificar:** ripple, elevación Material física, teclado, progress de scan, gráficos como formas estáticas (donut + barras), status bar de sistema (hora fija 15:46).

**Prohibido:** hex sueltos en pantallas si existe variable; reconstruir iconos con rectángulos rotados; mezclar Roboto e Inter; “mejorar” el Dark de las cards pastel.

## Implementación Figma (orden)

No hay `.figma.ts` ni `@FigmaConnect`. Tras `whoami` + `create_new_file`:

1. Foundations: colección + text/effect styles.
2. Components: uno (o un set) por llamada `use_figma`, screenshot.
3. Cada pantalla Light: wrapper 360×800 con placeholders (AppBar, Body, BottomNav) → reemplazar sección a sección.
4. Dark: duplicar frames y aplicar modo Dark; screenshot de Inicio y una segunda pantalla para validar pasteles.

Skills: `figma-create-new-file`, `figma-use`, `figma-generate-design`, `figma-generate-library` (componentes nuevos). `generate_figma_design` no aplica (no es web).

## Verificación

- Screenshot de cada frame Light contra el XML (orden de bloques, copy, radios).
- Inicio Dark: AppBar `#7E6BC4`, fondo `#1C1B1F`, card conexión sigue `#F3E5F5`.
- Barra inferior presente en las 8 pantallas; selección correcta en las 4 top-level.
- Diálogos solo sobre Archivos.
- Ningún texto “Title” / “Button” de placeholder de componente.
