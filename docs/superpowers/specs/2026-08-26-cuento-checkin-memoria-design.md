# Check-in de cuento, reflexión y memoria LLM — diseño

Fecha: 2026-08-26  
Producto: peluche TEO (Pi 5) + app Android MiCompañero  
Estado: aprobado en conversación; implementación en `main` sin commit hasta que Teo lo pida

## Problema

TEO lee el PDF entero en un solo turno (micrófono tapado). El nene no puede cortar. Al final no hay pregunta sobre el texto. El LLM no ve el cuento (lo lee Piper) y solo recuerda 2–4 turnos de fallback, no el resto del robot.

## Objetivo

1. Entre bloques: “¿Seguimos?”. **No / basta / parar** corta. **Silencio ~6 s** o sí/dale (u otra cosa que no sea corte) sigue el PDF sin reescribirlo.
2. Al **último** bloque: una pregunta corta del texto (LLM; si falla, plantilla). El nene responde; TEO comenta una frase; “¿Querés otro o paramos?”.
3. Memoria compartida: **10 conversaciones** (10 pares nene+TEO) para **todo** el robot (Groq y local).
4. Inicio: la misma card mint muestra el libro cuando se está leyendo, con Play y Stop.

## Fuera de alcance

- Preguntas de comprensión con LLM **entre** párrafos.
- Pausar y retomar a mitad (Play en cuento = reinicio).
- OCR. Chips en Archivos. Dark mode.

## Lectura (StoryEngine)

Estados: `idle` → `offering` → `checking_in` (hay más bloques) → `reflecting` (último bloque ya dicho) → `awaiting_more` → `idle`.

`is_active`: offering, checking_in, reflecting, awaiting_more. En esos estados el texto del nene va al engine, no al LLM (salvo `reflecting`, ver abajo).

Cada turno de lectura emite **un** `story_chunk`, no la lista completa. Si quedan más: `story_checkin = "¿Seguimos?"`. Si es el último: `story_need_reflection` + `story_digest` (~400 caracteres del texto).

El VAD no genera turno si no hay habla: un **timer de 6 s** en `AudioWorker` llama `advance_silence()`. Un contador de generación invalida el timer si llega STT.

Corte: mismas frases que `_wants_exit` (basta, parar, no quiero más, chau, …).

## Reflexión

Tras el último bloque, el worker pide al LLM **una** pregunta (máx. ~15 palabras, no narrar). Fallback: “¿Qué parte te gustó más?”.

Respuesta del nene (`reflecting`): LLM comenta una frase (con historial + digest). Silencio 6 s: no insiste. Basta: cierra. Después: `awaiting_more` y “¿Querés otro o paramos?” como hoy.

## Memoria

Módulo `conversation_memory.py`, `MAX_TURNS = 10` (20 mensajes). Lo usan Groq y el local. Se registra cada turno de `_handle_segment` con habla del nene, **excepto** los que solo avanzan un párrafo (`story_chunk` sin reflexión). Juegos, música, offering y charla sí.

Local: `n_ctx=2048`. Si el prompt no entra, se recortan turnos viejos, no el digest.

`FallbackLLM` / `CloudLLM` **leen** el buffer; no duplican historial interno.

## Inicio

Título de sección: **Ahora**. Misma card.

| Estado | Línea | Play | Stop |
|---|---|---|---|
| Nada | Nada sonando | última canción | para música y cuento |
| Canción | filename | esa / última | idem |
| Cuento | título | reinicia ese `id` | corta lectura + TTS restante del cuento |

Cuento y música no a la vez.

`GET /api/status`: `currently_reading: {id, title} | null` además de `currently_playing`.

`POST /api/stories/play` `{id}`. `POST /api/stories/stop`. Stop de música también cancela cuento.

## Errores

- LLM caído: plantilla de pregunta / “Qué lindo lo que contaste.”
- Cuento borrado a mitad: “Ese ya no está.”
- Play sin id / id inválido: 404.
- Peluche offline: snackbar actual.

## Pruebas

- Engine: un bloque → checkin; silencio avanza; basta corta; último → reflecting; digest ≤ 400.
- `ConversationMemory` recorta a 10 turnos.
- Tests de historial en `test_full.py` alineados a 10 turnos / 20 mensajes.
- Manual: card Ahora con título del libro; Stop corta; Play reinicia.
