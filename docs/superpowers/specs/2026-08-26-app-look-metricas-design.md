# Look unificado + copy parental en Métricas — diseño

Fecha: 2026-08-26  
Producto: app Android MiCompañero (padres, primera infancia)  
Estado: aprobado en conversación; implementación en `main` sin commit hasta que Teo lo pida

## Problema

Inicio y Archivos ya usan el sistema visual (padding 16 dp, `Widget.App.CardView` / `.Colored`, botones ≥ 48 dp). Rutinas, Agenda, Métricas y Config no: hay botones de 40 dp, “+ Agregar” a 13 sp, cards programáticas con radio 12 dp, y Métricas habla con jerga de pilares (cognitivo, emocional, vincular). Quedan layouts de plantilla Navigation Drawer (`fragment_transform`, `item_transform`) que no se inflan.

## Objetivo de esta iteración

Unificar el look de **Rutinas, Agenda, Métricas y Config** con Inicio, y que un padre lea Métricas sin jerga de desarrollo. Borrar los dos layouts muertos de plantilla.

Criterio de éxito: esas cuatro pantallas tienen padding 16 dp, cards del estilo de la app y controles ≥ 48 dp; Métricas usa la copy aprobada; no quedan `fragment_transform.xml` ni `item_transform.xml`.

## Fuera de alcance

- Dark mode fino, estados press extra, sombras premium, animaciones ricas.
- Chips Cuentos | Canciones dentro de Archivos.
- Cambiar navegación (barra, engranaje, Ver detalle).
- APIs nuevas en la Pi.
- Borrar `layout-w600dp` / `layout-w1240dp` de `activity_main`, `content_main` o `app_bar_main` (sí se usan).
- Rediseñar Inicio o Archivos (ya alineados).
- Quitar el FAB **+** de Rutinas (es el alta de rutina, no el de celebrar).
- Quitar el banner de debug de Config.

## Look (las cuatro pantallas)

Sistema ya definido en `themes.xml` / `dimens.xml`:

- Padding de pantalla: 16 dp.
- Cards lista: `Widget.App.CardView` (radio 16 dp, elevation 2 dp, `contentPadding` 16 dp) o los `dimen` equivalentes (`card_corner_radius`, `card_elevation`, `card_padding`) cuando la card se arma en código.
- Cards de acento: `Widget.App.CardView.Colored`.
- Títulos de sección: `TextAppearance.App.SectionTitle`.
- Botones y acciones táctiles: `minHeight` 48 dp (Hoy / Semana / Mes; Agregar turno; Conectar / Aplicar en Config; borrar turno).

Rutinas: el FAB se queda. Las filas del Recycler usan las mismas medidas de card (hoy radio 16 y elevation 2, pero padding vertical 12 dp → 16 dp).

Agenda: cards de turno alineadas al mismo radio/padding (hoy radio 12 dp). El botón de sección deja de ser “+ Agregar” a 13 sp; texto `@string/medical_add_appointment` (“Agregar Turno”), altura mínima 48 dp.

Config: ya tiene 16 dp y cards. Solo se suben los botones a 48 dp y se corrigen labels que muestran el literal `@string/...` (volumen, brillo, modo noche). El banner debug no se toca.

## Copy de Métricas

Toolbar (hoy `menu_metrics` = “Métricas”) y título de recurso `metrics_title`: **Cómo estuvo**.

| Recurso / texto actual | Copy |
|---|---|
| Panel de Métricas / Métricas (toolbar) | Cómo estuvo |
| Distribución por Pilar | En qué anduvo |
| Emocional | Cómo se sintió |
| Cognitivo | Juego y charla |
| Vincular | Con vos |
| Autonomía | Haciendo solo |
| Interacciones Diarias | Veces que hablaron |
| Progreso de Vocabulario | Palabras |
| Alertas (card resumen) | Avisos |

Los cuatro nombres de pilar van en una **leyenda** debajo del donut (color + texto). El donut sigue mostrando solo el total en el centro; no dibuja labels.

No se cambia la copy de Inicio (`dashboard_mood`, etc.). Los números de resumen (Interacciones, Tiempo de juego, Juegos, Rutinas) se quedan.

Strings viejos de jerga (`metrics_cognitive_title`, `metrics_emotional_title`, `metrics_social_title`) se actualizan a la copy nueva o se dejan de usar; no debe quedar “Desarrollo Cognitivo/Emocional/Vincular” visible.

## Basura de plantilla

Borrar:

- `app/src/main/res/layout-w600dp/fragment_transform.xml`
- `app/src/main/res/layout-w600dp/item_transform.xml`

Quitar `item_transform_image_length` de `values-w600dp/dimens.xml` y `values-w936dp/dimens.xml`. Si `values-w936dp/dimens.xml` queda vacío, se borra el archivo.

No tocar: `layout-w600dp/activity_main.xml`, `content_main.xml`, `app_bar_main.xml`; `layout-w1240dp/*`.

## Datos y errores

Sin endpoints nuevos. Sin cambio de ViewModels de métricas más allá de pasar las labels nuevas al donut (siguen sin pintarse; la leyenda es XML/strings).

Estados vacíos: “Sin datos” del donut/barras y `metrics_no_data` se mantienen.

## Accesibilidad

- Periodo, Agregar, acciones de Config y borrar turno: área mínima 48×48 dp.
- Leyenda del donut: texto, no solo color.
- Sin librerías de motion nuevas.

## Pruebas (manual; no hay suite UI)

- Rutinas: lista con cards 16 dp; FAB + abre alta; vacío muestra hint.
- Agenda: Agregar ≥ 48 dp; cards de turno radio 16; borrar usable.
- Métricas: toolbar “Cómo estuvo”; Hoy/Semana/Mes 48 dp; leyenda con los cuatro nombres; no aparece “pilar”, “cognitivo”, “vincular”, “emocional” como título de desarrollo; Avisos; Veces que hablaron; Palabras.
- Config: botones 48 dp; volumen/brillo/noche muestran el texto del string, no `@string/...`; debug banner intacto.
- Tablet: shell `w600`/`w1240` sigue abriendo; no hay pantalla Transform.

## Futuro (documentado, no implementar)

1. Dark mode coherente y estados press.
2. Animaciones de entrada.
3. Chips Cuentos | Canciones si la biblioteca crece.

## Archivos de código previstos (orientativo)

Modificar: `strings.xml`, `fragment_metrics.xml`, `MetricsFragment.kt`, `fragment_medical.xml`, `MedicalFragment.kt`, `RoutinesFragment.kt` (adapter), `fragment_config.xml`, dimens `w600`/`w936`.

Borrar: `fragment_transform.xml`, `item_transform.xml`.
