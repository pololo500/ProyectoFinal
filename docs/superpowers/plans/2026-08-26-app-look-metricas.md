# Look unificado + copy Métricas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unificar look de Rutinas, Agenda, Métricas y Config con Inicio; copy parental en Métricas; borrar layouts `transform` de plantilla.

**Architecture:** Reutilizar `Widget.App.CardView` / `dimen` `card_*` existentes. Copy solo en `strings.xml` + leyenda XML bajo el donut. Cards programáticas (rutinas, turnos) leen los mismos `dimen`. Sin APIs nuevas.

**Tech Stack:** Android Kotlin, Material, ViewBinding.

## Global Constraints

- Paleta actual. Sin Tailwind. Sin FAB de celebrar. El FAB de rutinas se queda.
- Botones táctiles ≥ 48 dp. Cards lista: radio 16 dp, elevation 2 dp, padding 16 dp.
- Copy de Métricas exactamente la de la spec. No jerga cognitivo/emocional/vincular visible.
- No borrar shell tablet `activity_main` / `content_main` / `app_bar`.
- No commits salvo que Teo lo pida. Trabajar en `main`.

## Archivos

- Modify: `ProyectoAndroid/app/src/main/res/values/strings.xml`
- Modify: `ProyectoAndroid/app/src/main/res/layout/fragment_metrics.xml`
- Modify: `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/metrics/MetricsFragment.kt`
- Modify: `ProyectoAndroid/app/src/main/res/navigation/mobile_navigation.xml` (label → `@string/metrics_title`)
- Modify: `ProyectoAndroid/app/src/main/res/layout/fragment_medical.xml`
- Modify: `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/medical/MedicalFragment.kt`
- Modify: `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/routines/RoutinesFragment.kt`
- Modify: `ProyectoAndroid/app/src/main/res/layout/fragment_config.xml`
- Modify: `ProyectoAndroid/app/src/main/res/values-w600dp/dimens.xml`
- Delete: `ProyectoAndroid/app/src/main/res/layout-w600dp/fragment_transform.xml`
- Delete: `ProyectoAndroid/app/src/main/res/layout-w600dp/item_transform.xml`
- Delete: `ProyectoAndroid/app/src/main/res/values-w936dp/dimens.xml` (solo contenía `item_transform_image_length`)

---

### Task 1: Strings y toolbar de Métricas

**Files:**
- Modify: `ProyectoAndroid/app/src/main/res/values/strings.xml`
- Modify: `ProyectoAndroid/app/src/main/res/navigation/mobile_navigation.xml`

- [ ] **Step 1: Actualizar strings**

`menu_metrics` y `metrics_title` → `Cómo estuvo`.  
`metrics_interaction_chart` → `Veces que hablaron`.  
`metrics_vocabulary_title` → `Palabras`.  
`metrics_cognitive_title` → `Juego y charla`.  
`metrics_emotional_title` → `Cómo se sintió`.  
`metrics_social_title` → `Con vos`.  
`metrics_emotion_chart` → `Cómo se sintió` (no se muestra hoy; sin jerga).

Agregar:

```xml
<string name="metrics_pillar_title">En qué anduvo</string>
<string name="metrics_pillar_emotional">Cómo se sintió</string>
<string name="metrics_pillar_cognitive">Juego y charla</string>
<string name="metrics_pillar_social">Con vos</string>
<string name="metrics_pillar_autonomy">Haciendo solo</string>
<string name="metrics_alerts_label">Avisos</string>
```

- [ ] **Step 2: Nav label**

En `mobile_navigation.xml`, `nav_metrics` `android:label="@string/metrics_title"`.

---

### Task 2: Layout Métricas (48 dp, copy, leyenda)

**Files:**
- Modify: `ProyectoAndroid/app/src/main/res/layout/fragment_metrics.xml`
- Modify: `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/metrics/MetricsFragment.kt`

- [ ] **Step 1: Periodo y Avisos**

Hoy/Semana/Mes: `android:layout_height="48dp"` y `android:minHeight="48dp"`.  
Card de crisis: `android:text="@string/metrics_alerts_label"`.  
Título pilar: `@string/metrics_pillar_title` (reemplaza hardcoded “Distribución por Pilar”).

- [ ] **Step 2: Leyenda bajo el donut**

Dentro de la card del donut, `LinearLayout` vertical: chart + cuatro filas (cuadrado 12 dp del color del arco + TextView del string de pilar). Colores, en este orden: `card_emotion_alert`, `tertiary`, `primary_light`, `card_emotion_happy`.

- [ ] **Step 3: Labels en Kotlin**

`setData(..., listOf(getString(R.string.metrics_pillar_emotional), ...), ...)`.

---

### Task 3: Agenda y Rutinas (cards + 48 dp)

**Files:**
- Modify: `fragment_medical.xml`, `MedicalFragment.kt`, `RoutinesFragment.kt`

- [ ] **Step 1: Botón Agregar**

`minHeight` 48 dp, quitar `textSize` 13 sp, texto `@string/medical_add_appointment`.

- [ ] **Step 2: Card de turno**

Radio/elevation/padding desde `R.dimen.card_corner_radius`, `card_elevation`, `card_padding`. Botón borrar `minWidth`/`minHeight` 48 dp.

- [ ] **Step 3: Card de rutina**

En `RoutineAdapter.onCreateViewHolder`, mismos `dimen` (padding 16 en los cuatro lados). FAB no se toca.

---

### Task 4: Config 48 dp + labels rotos; borrar transform

**Files:**
- Modify: `fragment_config.xml`, `values-w600dp/dimens.xml`
- Delete: layouts transform + `values-w936dp/dimens.xml`

- [ ] **Step 1: Config**

`btn_auto_scan`, `btn_save_ip`, `btn_apply_config`: `android:minHeight="48dp"`.  
Labels: `@string/config_volume_label`, `@string/config_brightness_label`, `@string/config_night_mode` (sin literal `@string/...`). Banner debug intacto.

- [ ] **Step 2: Borrar plantilla**

Borrar `fragment_transform.xml`, `item_transform.xml`. Quitar `item_transform_image_length` de `values-w600dp`. Borrar `values-w936dp/dimens.xml`.

- [ ] **Step 3: Verificar**

Grep: no quedan `TransformFragment`, `item_transform`, “Distribución por Pilar”, “Desarrollo Cognitivo”.  
Si hay JDK: `./gradlew :app:assembleDebug` desde `ProyectoAndroid`. Si no hay JDK, anotarlo y no afirmar que compiló.

Ver spec `docs/superpowers/specs/2026-08-26-app-look-metricas-design.md`.
