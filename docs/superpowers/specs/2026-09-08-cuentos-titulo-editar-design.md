# Cuentos: título al subir y edición desde el celular

Fecha: 2026-09-08  
Producto: peluche TEO (Raspberry Pi) + app parental Android  
Estado: contrato congelado para implementación en paralelo (Pi y Android no se pisan)

## Objetivo

1. Al subir un PDF desde el celular, el adulto **elige el nombre** del cuento.
2. Desde la lista de cuentos se puede **abrir** uno, ver el texto extraído, y **guardar** cambios de título y texto (por cortes malos de pypdf).

## Fuera de alcance

- OCR, re-subir PDF, historial de versiones.
- Cambiar `StoryEngine` / Piper / intents del nene.
- Nuevo ítem en la barra inferior.
- Commit git (el usuario no lo pidió).
- Arrancar `app.py` en la Pi.

## Contrato HTTP (obligatorio, idéntico en ambos lados)

Auth: igual que el resto (`X-Robot-Token` si hay pairing). CORS/OPTIONS igual.

### POST `/api/stories/upload`

Sin cambios de body: PDF crudo, `Content-Type: application/octet-stream`, `X-Filename` URL-encoded.

**Nuevo header opcional:** `X-Story-Title` (URL-encoded UTF-8).

- Si el header existe y, tras `unquote` + `strip`, no está vacío: ese es el título (máx. **80** caracteres; recortar, no rechazar).
- Si falta o queda vacío: se conserva `title_from_filename_and_text` (comportamiento actual).
- Validación de cuento infantil **igual** que ahora. Respuesta igual: HTTP 200 `{status: ready|rejected, ...}`.

Firma Python: `ingest_pdf(pdf_bytes, filename, stories_dir=None, title: str | None = None)`.

### GET `/api/stories/{id}`

Nuevo. `id` URL-decoded, saneado con `Path(id).name` (igual que delete).

**200:**

```json
{ "id": "...", "title": "...", "word_count": 123, "created_at": "...", "text": "..." }
```

`text` es el `.txt` completo UTF-8.

**404:** `{ "error": "Cuento no encontrado" }`

En `do_GET`, **después** de `path == "/api/stories"` (lista), agregar `path.startswith("/api/stories/")`. No colisiona con POST `/api/stories/play`.

### PUT `/api/stories/{id}`

Nuevo `do_PUT` (mismo `_authorized(..., mutating=True)` que POST/DELETE).

JSON:

```json
{ "title": "opcional", "text": "opcional" }
```

Al menos uno de los dos. Título: strip, no vacío, máx. 80. Si viene `text`, correr `validate_children_story`; si falla: HTTP **200** `{ "status": "rejected", "reason": "..." }` (mismo patrón que upload).

**Importante:** el `id` **no cambia**. Se reescriben `{id}.txt` y `{id}.json`; se conserva `created_at`; se actualiza `word_count` y `title`.

**200 OK:** `{ "status": "ok", "id", "title", "word_count" }`  
**400:** JSON inválido o ambos campos ausentes / título vacío.  
**404:** no existe.

### DELETE `/api/stories/{id}`

Sin cambios.

## Raspberry Pi — archivos

- `ProyectoParaRasperrypiV5/story_library.py` — `ingest_pdf(..., title=)`, `update_story(story_id, title=None, text=None)`.
- `ProyectoParaRasperrypiV5/api_server.py` — header, GET uno, PUT.
- `ProyectoParaRasperrypiV5/test_stories.py` — TDD **antes** del código: título override; update título; update texto; update no cambia id; texto inválido rejected; GET/update 404.

No tocar `workers.py` ni `story_engine.py`.

Tras verde: SFTP a `teo@192.168.0.136`, `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`, script `C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py`. Contraseña **solo** env `PI_SSH_PASS` (sesión; no escribirla en archivos). **No** arrancar `app.py`.

## Android — archivos

Solo `ProyectoAndroid/`.

- `RobotApiClient.uploadStory(filename, data, title: String? = null)` — si title no es null/blank, header `X-Story-Title` URL-encoded.
- `getStory(id)`, `updateStory(id, title: String?, text: String?)` (PUT JSON).
- `RobotConnectionManager` wrappers async.
- `StoriesFragment` / `StoriesViewModel`:
  1. Tras elegir PDF: diálogo **Nombre del cuento** (EditText, prefijo = stem del archivo sin `.pdf`). Cancelar = no subir. Aceptar = `uploadPdf(filename, bytes, title)`.
  2. Tocar el **título** de un ítem (no el botón Borrar) abre editor: título + texto multilínea scrolleable (layout propio, no un AlertDialog de una línea). Cargar con GET. Guardar = PUT. Cancelar cierra. Snackbar con `reason` si rejected.
- Strings en `strings.xml` (español).
- No tocar música ni otras pestañas más de lo necesario para el cliente HTTP.

## Pruebas

Pi: `python test_stories.py` desde `ProyectoParaRasperrypiV5` (y unittest si agregás módulo).  
Android: no hay suite de red; no romper compile. Si agregás test de ViewModel/parsing, bien.

## Rollback

Quitar header y GET/PUT; Android vuelve a subir sin diálogo de nombre y sin editor.
