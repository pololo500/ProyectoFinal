# Reporte Pi: título al subir y edición de cuentos

Fecha: 2026-09-08  
Alcance: solo `ProyectoParaRasperrypiV5/` (contrato HTTP de `2026-09-08-cuentos-titulo-editar-design.md`)  
Estado: **DONE**

## Qué se implementó

1. `ingest_pdf(..., title: str | None = None)`: si `title` tras `strip` no está vacío, se usa (máx. 80, recorte); si falta o queda vacío, se conserva `title_from_filename_and_text`.
2. Header `X-Story-Title` en `POST /api/stories/upload`: URL-decoded (`unquote` + `strip`); vacío → se ignora.
3. `StoryLibrary.update_story(story_id, title=None, text=None)`: el `id` no cambia; `created_at` se conserva; `word_count` se recalcula solo si viene `text`; si viene `text` se corre `validate_children_story`.
4. `GET /api/stories/{id}` y `PUT /api/stories/{id}` (`do_PUT`). Routing GET: path exacto `/api/stories` primero, después prefix `/api/stories/`.
5. Respuestas del contrato: 200 `{status: ok|rejected,...}`, 404 `{error: "Cuento no encontrado"}`, 400 JSON inválido / ambos campos ausentes / título vacío.

No se tocó `ProyectoAndroid/`, `workers.py`, `story_engine.py` ni `app.py`. No hay commit git. No se arrancó `app.py`. SFTP omitido a pedido explícito del padre (lo hace después).

## TDD (rojo → verde)

Los tests nuevos se escribieron en `test_stories.py` **antes** del código de producción. No se agregó unittest aparte: todo corre con `python test_stories.py`.

### RED 1 — `ingest_pdf` no aceptaba `title`

```
  [OK] pdf enorme se rechaza
Traceback (most recent call last):
  File "...\test_stories.py", line 520, in <module>
    test_ingest_title_override()
  ...
TypeError: ingest_pdf() got an unexpected keyword argument 'title'
```

Código mínimo: parámetro `title` + recorte 80 / fallback al nombre del archivo o primera línea.

### RED 2 — no existía `update_story`

Tras verde de ingest:

```
  [OK] título largo se recorta a 80
Traceback (most recent call last):
  File "...\test_stories.py", line 523, in <module>
    test_update_story_title()
  ...
AttributeError: 'StoryLibrary' object has no attribute 'update_story'. Did you mean: 'save_story'?
```

Código mínimo: `update_story` con id estable, `created_at` intacto, validación si hay texto, `None` si no existe.

### RED 3 — HTTP GET/PUT ausentes

```
  [OK] update de id inexistente es None
  [FAIL] GET cuento 200  ->  404
  [FAIL] GET incluye texto  ->  dict_keys(['error'])
  [FAIL] GET incluye id y título
  [OK] GET 404 status
  [FAIL] GET 404 mensaje  ->  {'error': 'Endpoint no encontrado'}
  [OK] GET lista no se rompe
Traceback ... test_http_put_story_and_404
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

GET de un id existente caía en 404 genérico (`Endpoint no encontrado`). PUT no tenía `do_PUT` (respuesta no JSON / 501).

Código mínimo: `_handle_get_story`, `do_PUT` + `_handle_put_story`, header `X-Story-Title` en upload.

### GREEN

Comando (cwd `ProyectoParaRasperrypiV5`):

```
python test_stories.py
```

Salida final (corrida de verificación, 2026-09-08):

```
=== CUENTOS ===
  [OK] cuento narrativo se acepta
  ...
  [OK] ingest con título override queda ready
  [OK] ingest usa el título pedido
  [OK] título vacío cae al texto/archivo
  [OK] título largo se recorta a 80
  [OK] update título ok
  [OK] update título cambia el nombre
  [OK] json guarda el título nuevo
  [OK] update texto ok
  [OK] texto nuevo persistido
  [OK] word_count se recalcula
  [OK] update no cambia id
  [OK] created_at se conserva
  [OK] sigue existiendo un solo json
  [OK] texto inválido rejected
  [OK] rejected trae reason
  [OK] texto original intacto
  [OK] título original intacto
  [OK] update de id inexistente es None
  [OK] GET cuento 200
  [OK] GET incluye texto
  [OK] GET incluye id y título
  [OK] GET 404 status
  [OK] GET 404 mensaje
  [OK] GET lista no se rompe
  [OK] PUT título 200
  [OK] PUT no cambia id
  [OK] PUT devuelve título
  [OK] PUT texto inválido 200 rejected
  [OK] PUT rejected trae reason
  [OK] PUT 404 status
  [OK] PUT 404 mensaje
  [OK] PUT sin campos 400
  [OK] PUT 400 trae error
  [OK] PUT JSON inválido 400
  [OK] upload header 200 ready
  [OK] upload decodifica X-Story-Title
  ...
  [OK] mínimo 80 palabras

PASS=83 FAIL=0
```

Exit code: **0**. PASS=**83** FAIL=**0**. No hay suite unittest extra.

Los tests de ingest/upload con título stubbean `extract_pdf_text` (el override de título no depende de pypdf). GET/PUT HTTP levantan `HTTPServer` en `127.0.0.1:0` con `STORIES_DIR` temporal y token de pairing vacío.

## Contrato HTTP (cumplimiento)

| Caso | Spec | Implementación |
|------|------|----------------|
| `POST /api/stories/upload` + `X-Story-Title` | unquote + strip; no vacío → título máx. 80 recortado | `api_server._handle_post_stories_upload` + `ingest_pdf(..., title=)` |
| Header ausente o vacío | `title_from_filename_and_text` | sí |
| Validación infantil | igual que antes; HTTP 200 `ready`/`rejected` | sin cambios de status |
| `GET /api/stories` | lista | path exacto primero |
| `GET /api/stories/{id}` | 200 con `id,title,word_count,created_at,text` | `_handle_get_story` |
| GET 404 | `{ "error": "Cuento no encontrado" }` | literal |
| `PUT /api/stories/{id}` | JSON título y/o texto; id estable | `do_PUT` + `update_story` |
| PUT heurística falla | HTTP **200** `{status: rejected, reason}` | sí; no se reescriben archivos |
| PUT 200 ok | `{status: ok, id, title, word_count}` | sí |
| PUT 400 | JSON inválido, ambos ausentes, título vacío | `"JSON inválido"` / `"Falta título o texto"` / `"Título vacío"` (el spec no congela el string de 400, sí el código) |
| PUT 404 | `{ "error": "Cuento no encontrado" }` | literal |
| Auth | `_authorized(..., mutating=True)` en PUT igual que POST/DELETE | sí |
| DELETE | sin cambios | sin cambios |

CORS: se agregó `PUT` a `Allow-Methods` y `X-Story-Title` a `Allow-Headers`. El spec dice “CORS/OPTIONS igual”; Android no usa CORS. Es una extensión mínima para que el contrato nuevo funcione también desde navegador.

## Archivos tocados

- `ProyectoParaRasperrypiV5/story_library.py`
- `ProyectoParaRasperrypiV5/api_server.py`
- `ProyectoParaRasperrypiV5/test_stories.py`
- `docs/superpowers/specs/2026-09-08-cuentos-titulo-editar-pi-report.md` (este reporte)

## Verificación

```
cd ProyectoParaRasperrypiV5
python test_stories.py
```

**PASS=83 FAIL=0** (exit 0).

## Fuera de este lado

- Android: no tocado (otro agente).
- SFTP a la Pi: no hecho (el padre lo hace después). Hace falta copiar los tres `.py` y reiniciar el proceso que ya corre `app.py`; este agente no arrancó `app.py`.
- No se escribieron secretos ni contraseñas.

## Concerns

Ninguno que bloquee el contrato. Notas:

1. Mensajes de error 400 no están congelados en el spec; se usaron strings en español alineados al resto de la API.
2. CORS Allow-Methods/Headers se extendió con PUT y `X-Story-Title`.
3. Los tests de título en upload no generan un PDF real; stubbean la extracción de texto a propósito.
