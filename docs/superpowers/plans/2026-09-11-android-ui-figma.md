# MiCompañero Android → Figma Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Figma MCP is sequential; no parallel `use_figma`). Spec: `docs/superpowers/specs/2026-09-11-android-ui-figma-design.md`.

**Goal:** Archivo Figma nuevo con tokens Light/Dark, componentes y las 8 pantallas de teléfono (+ 2 diálogos) documentando el UI actual de MiCompañero.

**Architecture:** Colecciones Primitives (1 modo) + Color (Light/Dark) + Spacing. Componentes locales ligados a variables. Pantallas 360×800 como instancias. Dark = mismo frame, modo Dark. Sin Code Connect. Sin drawer (teléfono usa barra inferior).

**Tech Stack:** Figma Plugin API via `use_figma` / `$fig`. Skills: `figma-create-new-file`, `figma-use`, `figma-generate-library`, `figma-generate-design`.

## Global Constraints

- Documentar, no rediseñar. Copy de `strings.xml`. Hex de `colors.xml` / `themes.xml`.
- Frames 360×800. Pasteles de cards iguales en Dark.
- Roboto; si no está, Inter (una sola familia en el archivo).
- Sin commits. Ledger: `docs/superpowers/plans/figma-micompanero-state.json`.
- `use_figma` siempre secuencial. IDs solo del ledger, nunca inventados.
- Si `addMode("Dark")` falla (plan Starter): parar y avisarle a Teo.

## Archivos

- Crear: archivo Figma **MiCompañero — Android UI** (drafts)
- Crear: `docs/superpowers/plans/figma-micompanero-state.json`
- No modificar código Android

---

### Task 1: Archivo Figma + páginas

**Produces:** `fileKey`, `file_url`, páginas Foundations / Components / Screens Light / Screens Dark

- [ ] **Step 1:** `whoami`. Si hay un solo plan, usar su `key`. Si hay varios, preguntar a Teo.
- [ ] **Step 2:** `create_new_file` con `fileName: "MiCompañero — Android UI"`, `editorType: "design"`, `planKey` del paso 1.
- [ ] **Step 3:** Renombrar página default a Foundations; crear Components, Screens / Light, Screens / Dark. Guardar IDs en el ledger.

---

### Task 2: Tokens

**Produces:** collections + variable IDs en el ledger

- [ ] **Step 1:** Collection `Primitives` modo `Value`. Colores raw (primary `#6750A4`, primary-light `#7E6BC4`, primary-dark `#4F378B`, secondary, tertiary, backgrounds, pasteles, status, white, black). `scopes: []`. Code syntax ANDROID `@color/...`.
- [ ] **Step 2:** Collection `Color` modos Light + Dark. Semánticos aliasados a primitivos según tabla de la spec (`color/primary`, `color/background`, `color/card-lavender`, etc.). Scopes: fills vs TEXT_FILL.
- [ ] **Step 3:** Collection `Spacing` modo `Value`: `space/4|8|12|16|24`, `radius/8|12|16|20`. Scopes GAP / CORNER_RADIUS / PADDING.
- [ ] **Step 4:** Text styles (Roboto o Inter): Section Title 18 Bold, Card Title 16 Bold, Card Subtitle 13 Regular, Metric Value 28 Bold, Body 16 Regular, AppBar Title 20 Medium, Bottom Nav 12 Medium. Effect style `elevation/card`.
- [ ] **Step 5:** Verificar: listar variables + modos. Screenshot de Foundations (swatches Light vs Dark).

---

### Task 3: Componentes

**Produces:** component IDs (Button, Card, ChipStatus, AppBar, BottomNav, FAB, ListRow, MetricTile, PeriodSelector, TextField, Switch, Slider, StatusBar, Dialog)

- [ ] Construir de a uno (o familia estrecha) con `$fig.component` / `$fig.variants`, bindings a variables, screenshot. Iconos SVG de drawables (teddy, home, routines, folder, medical, settings, celebrate, add). INSTANCE_SWAP para íconos, no una variante por ícono.

---

### Task 4: Pantallas Light

**Produces:** 8 frames 360×800 + 2 overlays en Screens / Light

Orden: Inicio → Cómo estuvo → Rutinas → Rutinas vacía → Archivos → Archivos vacío → Agenda → Configuración → diálogos sobre Archivos.

Cada pantalla: wrapper con placeholders AppBar / Body / BottomNav; reemplazar sección a sección; `.screenshot()`.

---

### Task 5: Pantallas Dark

- [ ] Duplicar los 8 frames (+ overlays) a Screens / Dark.
- [ ] Aplicar modo Dark de la colección Color.
- [ ] Screenshot Inicio Dark y Config Dark: AppBar `#7E6BC4`, fondo `#1C1B1F`, card conexión sigue `#F3E5F5`.

---

### Task 6: QA + crítica

Checklist de la spec (barra inferior, copy, pasteles, sin placeholder “Title”/“Button”, diálogos solo sobre Archivos). Corregir Critical/Important. Entregar URL + veredicto.
