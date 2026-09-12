# Reporte Android: título al subir PDF y edición de cuento

Fecha: 2026-09-08  
App: `ProyectoAndroid/` (app parental)  
Contrato: `docs/superpowers/specs/2026-09-08-cuentos-titulo-editar-design.md`  
Estado: **DONE_WITH_CONCERNS** — lado Android implementado y compilado; no se pudo verificar contra la Pi ni en dispositivo.

## Qué quedó hecho

### 1. Nombre al subir PDF

Después de elegir el PDF (cuando ya hay URI y bytes), aparece un diálogo **Nombre del cuento** (`dialog_story_name.xml`) con `EditText` prefijado con el stem del archivo (sin `.pdf`).

- **Cancelar**: no se sube nada.
- **Aceptar**: `uploadPdf(filename, bytes, title)` → POST `/api/stories/upload` con header `X-Story-Title` (solo si el título no está en blanco).

### 2. Editar un cuento ya cargado

Tocar la **fila/título** (no el botón Borrar) dispara GET `/api/stories/{id}`. Al llegar el JSON se abre un editor propio (`dialog_story_edit.xml`): título + texto multilínea scrolleable (no es un AlertDialog de una línea).

- **Guardar**: PUT `/api/stories/{id}` con `{title, text}`. Si `status == rejected`, Snackbar con `reason` y el editor sigue abierto.
- **Cancelar**: cierra sin guardar.
- **Borrar**: sin cambios de flujo (sigue pidiendo confirmación).

Música / bottom nav: no se tocó el flujo más que el cliente HTTP compartido (firma de `uploadStory` con parámetro opcional; llamadas existentes siguen compilando).

## Contrato HTTP (cliente)

Auth igual que el resto (`X-Robot-Token` si hay pairing). `HttpURLConnection`, sin Retrofit.

| Método | Ruta | Notas |
|--------|------|--------|
| POST | `/api/stories/upload` | Body PDF, `X-Filename` URL-encoded (igual que antes). Header opcional `X-Story-Title` URL-encoded UTF-8 **solo** si el título no es null/blank. `readTimeout` 60000. |
| GET | `/api/stories/{id}` | `id` URL-encoded igual que DELETE. |
| PUT | `/api/stories/{id}` | JSON `{title?, text?}`. Nuevo `doPut`. |
| DELETE | `/api/stories/{id}` | Sin cambios. |

Codificación de `X-Story-Title`: `URLEncoder.encode(..., "UTF-8")` y `+` reemplazado por `%20`, para que `urllib.parse.unquote` en la Pi conserve espacios (el `+` de form-encoding no lo decodifica `unquote`). El `id` en GET/PUT usa el mismo `URLEncoder.encode` que DELETE, sin ese replace.

## Archivos tocados

### Código

- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/network/RobotApiClient.kt` — `uploadStory(..., title)`, `getStory`, `updateStory`, `doPut`
- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/network/RobotConnectionManager.kt` — wrappers async `uploadStory(title)`, `fetchStory`, `updateStory`
- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/network/UrlEncoding.kt` — **nuevo**, encode de headers
- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/stories/StoryJson.kt` — **nuevo**, parseo GET/PUT, stem del PDF
- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/stories/StoriesViewModel.kt` — título en upload, `loadStory` / `saveStory`
- `ProyectoAndroid/app/src/main/java/com/example/aplicacionparacelular/ui/stories/StoriesFragment.kt` — diálogo de nombre + editor

### Layouts y strings

- `ProyectoAndroid/app/src/main/res/layout/dialog_story_name.xml` — **nuevo**
- `ProyectoAndroid/app/src/main/res/layout/dialog_story_edit.xml` — **nuevo**
- `ProyectoAndroid/app/src/main/res/values/strings.xml` — strings en español

### Tests / Gradle

- `ProyectoAndroid/app/src/test/java/com/example/aplicacionparacelular/ui/stories/StoryJsonTest.kt` — **nuevo** (sin red)
- `ProyectoAndroid/app/build.gradle.kts` — `testImplementation` de `org.json`
- `ProyectoAndroid/gradle/libs.versions.toml` — versión `org.json`

### Este reporte

- `docs/superpowers/specs/2026-09-08-cuentos-titulo-editar-android-report.md`

**No tocado:** `ProyectoParaRasperrypiV5/`, bottom nav, flujo de música (salvo el default param en `uploadStory`).

## Verificación local

- `JAVA_HOME` = JBR de Android Studio (`C:\Program Files\Android\Android Studio\jbr`)
- `:app:compileDebugKotlin` OK
- `:app:assembleDebug` OK (`BUILD SUCCESSFUL`)
- `:app:testDebugUnitTest` OK
  - `StoryJsonTest`: 4 tests, 0 failures (`parseDetail`, `parseUpdateStatus` ok/rejected, `pdfStem`, encode `%20`)
  - `ExampleUnitTest` existente también pasó

No hay emulador/dispositivo en esta sesión: la UI no se recorrió con clics reales.

## Cómo probar en la app

Requisito: la Pi debe exponer ya el contrato (header `X-Story-Title`, GET y PUT de un cuento). Emparejar el celular con el robot.

1. Abrir la pestaña **Cuentos**.
2. **Subir PDF** → elegir un PDF con texto.
3. Debe aparecer **Nombre del cuento** con el nombre del archivo sin `.pdf`.
4. **Cancelar**: la lista no cambia; no hay “Subiendo PDF...”.
5. Volver a elegir el PDF, cambiar el nombre (máx. 80) → **Aceptar**: Snackbar de subida y, si la Pi acepta, “Cuento listo: …” y el título nuevo en la lista.
6. Tocar el **título/fila** de un cuento (no Borrar): se carga el texto y se abre el editor (título + texto largo scrolleable).
7. Cambiar título y/o texto → **Guardar**: lista actualizada; el `id` no debe cambiar (eso lo garantiza la Pi).
8. **Cancelar** en el editor: cierra sin persistir.
9. Si el texto no pasa la validación infantil de la Pi: Snackbar con `reason`, editor sigue abierto.
10. **Borrar** sigue pidiendo confirmación y elimina.
11. Canciones (play/stop/subir/borrar) igual que antes.

## Concerns

1. **E2E no corrido.** Este trabajo asume el contrato en la Pi; si GET/PUT o el header no están desplegados, el editor falla (error HTTP) y el título custom no se aplica (el POST viejo ignora headers desconocidos).
2. **CORS en la Pi.** `Access-Control-Allow-Headers` hoy menciona `X-Filename` y no `X-Story-Title`. La app Android nativa no hace preflight; solo importa si alguien prueba el upload desde un browser.
3. **Sin prueba en dispositivo.** Layout del editor (85% de pantalla, texto con scroll) no se validó en un teléfono real ni con teclado.
4. **Timeout GET/PUT** = 10 s (igual que el resto de JSON). En LAN debería alcanzar; un `.txt` enorme podría cortar.
5. **Snackbar “Cargando cuento...”** aparece al tocar la fila, antes del editor. Es intencional (feedback de GET).
