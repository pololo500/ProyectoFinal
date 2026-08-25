# Cuentos desde PDF — diseño (iteración 1)

Fecha: 2026-08-24  
Producto: peluche TEO (Raspberry Pi) + app parental Android  
Estado: aprobado en conversación; pendiente de plan de implementación

## Problema

El nene pide un cuento y el pedido cae al LLM (local limitado o Groq). El modelo **inventa** el relato, se corta o se va de tema. No hay biblioteca de cuentos ni skill equivalente a música o juegos.

## Objetivo de esta iteración

El adulto carga un **PDF de texto** desde una pestaña **Cuentos** en la app. La Pi extrae el texto, lo valida con **heurística local** (sin Groq) y, si pasa, lo **publica**. Cuando el nene pide un cuento, una skill (`StoryEngine`) lista títulos, espera la elección y **lee el texto extraído en voz alta** (Piper), por párrafos. El LLM no narra.

## Fuera de alcance (iteración 1)

- Recontar o resumir el PDF con el LLM.
- Preguntas entre párrafos (opción C; ver [Futuro](#futuro-opción-c)).
- PDF escaneado (solo imagen) / OCR.
- Pausar y retomar a mitad del cuento.
- Convertir el PDF a audio en la subida.
- Editar el texto en la app.
- Barra inferior de Android: no se agrega ítem (sigue Inicio / Métricas / Rutinas).

## Arquitectura

Tres piezas, mismo patrón que la música:

1. **App Android** — pestaña propia (cajón + overflow), no dentro de Configuración. Sube PDF, lista estados, borra.
2. **API en la Pi** — `GET/POST/DELETE` de cuentos. Procesa el PDF en el servidor.
3. **StoryEngine** — máquina de estados como `GameEngine`. Intercepta el turno **antes** del LLM cuando el nene pide o está eligiendo/escuchando un cuento.

Almacenamiento en la Pi, carpeta `stories/` (junto al código, analogía de `music/`):

| Archivo | Rol |
| --- | --- |
| `{id}.txt` | Texto a leer (UTF-8) |
| `{id}.json` | Metadatos: `id`, `title`, `status` (`ready` \| `rejected`), `word_count`, `reject_reason` (si aplica), `created_at` |
| PDF original | Opcional durante el proceso; **se borra** tras extraer para no llenar la SD |

Un cuento `rejected` no se ofrece al nene. Puede quedar en la lista de la app para que el adulto vea el motivo y lo borre, o no persistir el `.txt` (solo metadatos de rechazo + mensaje). Preferencia: **no guardar el texto rechazado**; sí devolver el motivo en la respuesta del upload y, si se lista, un ítem `rejected` efímero no es obligatorio. **Decisión:** el `POST` de upload responde `ready` o `rejected` + motivo. Solo se persisten cuentos `ready`. La app muestra el error del upload en un snackbar/diálogo; la lista GET solo trae publicados.

## Flujo de datos (subida)

```
App elige PDF → POST /api/stories/upload (raw body + X-Filename)
  → Pi guarda temporal → extrae texto (pypdf)
  → limpia → heurística
  → OK: escribe {id}.txt + {id}.json, borra PDF, JSON {status: ready, id, title, word_count}
  → FAIL: borra temporal, JSON {status: rejected, reason} (HTTP 200 con status, no 500)
```

Límites: **8 MB**, **15 páginas**. Extensión `.pdf`. Nombre saneado como en música.

## Extracción y limpieza

- Biblioteca: `pypdf` (añadir a `requirements.txt`).
- Si no hay caracteres extraídos (escaneo): rechazo *“Este PDF no tiene texto para leer; subí uno que no sea foto de páginas.”*
- Limpieza: unir páginas, quitar líneas que son solo un número (página), encabezados/pies repetidos obvios.
- Título: `Path(filename).stem` con `_` → espacios. Si la primera línea del texto tiene ≤ 80 caracteres y no termina en punto, puede usarse como título; si no, el nombre de archivo.

## Heurística de cuento infantil (local, todas deben cumplirse)

1. ≥ 80 palabras y ≥ 3 oraciones (punto/`!`/`?`).
2. No parece documento administrativo: si hay muchos indicios de factura/manual (`total a pagar`, `factura`, `cuit`, `http://`, `%`) y pocos de narración (`había`, `capítulo`, nombres de personajes típicos no son obligatorios — usar una lista corta de *señales narrativas*: `había una vez`, `dijo`, `preguntó`, `capítulo`, `entonces`), rechazar. Umbral concreto en implementación: p. ej. ≥ 3 señales “documento” y 0 señales “narración” → rechazo.
3. Lista de **bloqueo** (palabra/frase, case-insensitive, español): violencia gráfica y contenido adulto / groserías fuertes. Lista cerrada en código (constante), no configurable en v1. Match → rechazo con motivo que **no recita** la palabra ofensiva: “El texto no parece adecuado para chicos.”
4. No es un muro técnico: proporción alta de dígitos o líneas tipo `copyright`.

Esto **no** reemplaza el criterio del adulto; solo filtra basura obvia.

## StoryEngine (nene)

Estados: `idle` → `offering` → `reading` → `idle` (vía `done` hablado).

### Activación

Intent nuevo en `intent_rules.json`, p. ej. `story_request`, ejemplos:

- contame un cuento / contame un cuento teo
- leeme un cuento / leéme un cuento
- quiero un cuento / un cuento por favor
- historia / narrame un cuento

Prioridad alta, como `song_request`. Si `StoryEngine` está en `offering` o `reading`, **todo** el texto del nene va al engine (como juego activo), no al LLM.

### offering

- 0 cuentos `ready`: “Pedile a mamá o papá que te suban un cuento desde el celular.” → `idle`.
- 1 cuento: nombra el título y pregunta si lo lee. “Sí / dale / ese / cualquiera” → `reading`. “No / basta / después” → `idle`.
- Varios: lista títulos (“Tengo A y B. ¿Cuál querés, o cualquiera?”). Match por palabras del título (mín. 3 letras, mismo criterio que juegos). “Cualquiera / ese / sí” → uno al azar. “No / basta / después” → `idle`. Si no matchea: **repite la lista una vez**; segundo fallo → “Después lo leemos.” → `idle`.

### reading

Lee el `.txt` **por párrafos** (split en líneas en blanco o bloques de ~2–3 oraciones si el párrafo es enorme). Piper habla cada bloque. Entre bloques, pausa corta. El micrófono **sigue bloqueado** mientras Piper habla (limitación actual documentada; no se resuelve en esta iteración).

Corte: “basta / parar / no quiero más / chau” (mismas ideas que `_wants_to_exit` de juegos) → deja de encolar párrafos, frase corta de cierre → `idle`. **No** se retoma a mitad: la próxima vez empieza de cero.

Si el archivo desaparece a mitad (borrado desde la app): “Ese ya no está.” → vuelve a `offering` si quedan otros, si no `idle`.

### done

Al terminar el texto: “¿Querés otro o paramos?” → otro / sí → `offering`; basta / no / silencio (un turno vacío no es obligatorio en v1; si no hay STT, el engine vuelve a `idle` al terminar el último párrafo **después** de la pregunta; si el nene no habla, el siguiente utterance no-cuento sale por el pipeline normal porque el engine ya está `idle`… **Ambigüedad resuelta:** después del último párrafo TEO dice la pregunta y queda **un turno** en `offering`-like `awaiting_more`. Si el siguiente utterance no es “otro/sí/un cuento”, o es “no/basta”, → `idle`. Si es pedido de cuento u “otro”, → `offering` de nuevo.

### LLM

- Prompt (Groq y fallback local): **no inventar cuentos**. Si piden un cuento, respuesta corta invitando a decir “contame un cuento” (la skill debería haber interceptado; esto es red de seguridad).
- No hay tag `[TELL_STORY]` en v1: la skill es por intent + engine, no por tag del LLM.

## API

Base: mismo servidor `api_server.py`, puerto 8080.

| Método | Ruta | Cuerpo | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/stories` | — | `{ "stories": [ { "id", "title", "word_count", "created_at" } ] }` solo `ready` |
| POST | `/api/stories/upload` | raw PDF, header `X-Filename` | `{ "status": "ready"\|"rejected", "id"?, "title"?, "word_count"?, "reason"? }` |
| DELETE | `/api/stories/{id}` | — | `{ "status": "ok" }` o 404 |

CORS / cleartext: igual que música.

## App Android

- Destino Navigation: `nav_stories`.
- Ítem en `navigation_drawer.xml` (junto a Médica) y en `overflow.xml` (mismo patrón que médica).
- Fragmento + ViewModel: lista, FAB o botón “Subir PDF”, swipe/borrar.
- Cliente: `RobotApiClient` + `RobotConnectionManager` (upload como `uploadMusic`: `X-Filename` URL-encoded, body bytes).
- Picker: `OpenDocument` / `GetContent` con `application/pdf`.
- Copy: “Subí un PDF con texto (no foto). TEO lo lee cuando el nene pide un cuento.”
- Rechazo: Snackbar con `reason`. Éxito: refrescar lista.

Permisos: los de lectura de documentos actuales bastan (SAF). No hace falta storage extra si se usa el picker.

## Errores

| Caso | Comportamiento |
| --- | --- |
| Pi / WiFi caído | Mismo mensaje de conexión que música |
| PDF > 8 MB o > 15 páginas | `rejected` + motivo |
| PDF sin texto | `rejected` + motivo de escaneo |
| Heurística | `rejected` + motivo genérico o específico no ofensivo |
| Upload cortado | No queda `.txt`/`.json` a medias (escribir a temp y rename) |
| Borrar mientras ofrece/lee | “Ese ya no está”; re-listar o `idle` |

## Pruebas (sin LLM, sin Piper real)

Módulo de dominio testeable (`story_library.py` + `story_engine.py` + `story_validate.py`):

- Extraer fixture PDF de texto corto → `ready`.
- Fixture “vacío/imagen” o texto factura → `rejected`.
- Palabra de bloqueo → `rejected`.
- Engine: 0 / 1 / N cuentos; “cualquiera”; match de título; “basta” en offering y (simulado) en reading; borrar id activo.

Tests en `ProyectoParaRasperrypiV5/test_*.py` al estilo existente (`test_full.py`), o archivo `test_stories.py`.

## Futuro (opción C) — no implementar ahora

Entre párrafos, una pregunta corta tipo “¿Te gustó el lobo?”. Si el nene dice que no o no hay respuesta clara, **seguir leyendo el texto del PDF sin reescribirlo**. El LLM no genera el cuento; como máximo genera la pregunta. Documentado para una iteración posterior.

## Dependencias y restricciones

- No subir Whisper a `medium`; no STT en la nube.
- Validación **sin Groq**.
- Piper/mic bloqueado durante TTS: se acepta en v1.
- Responder al usuario de este repo en español; nombre TEO del peluche vs Teo el desarrollador: en copy del nene/app, el robot es **TEO**.
