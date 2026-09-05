# Intents por keyword, el resto al LLM — diseño

Fecha: 2026-08-29  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

El `IntentDispatcher` elige un intent enlatado por cosine MiniLM contra `intent_rules.json`. Frases cortas o de otro tema ganan intents de cuidado.

Evidencia (log `debug_2026-08-29_18-53-28.txt`):

- `"Zanahoria."` → `body_hurt` (0.854); el TTS dijo *“Si duele mucho, mamá o papá”*. No fue `call_parent`; el copy enlatado habla de los padres. El segundo score era ~0.907 (homógrafo papa/papá).
- En la misma sesión: bichito → `school_day` / `emotion_fear`; batalla naval → `birthday_talk`; “No se me oculta nada” → `crisis_cry`.

El LLM ya puede avisar con `[NOTIFY_PARENT:razón]`, pero no ve esas frases porque el dispatcher se las queda. Si gana `call_parent`, `AudioWorker` notifica solo, sin el modelo.

## Objetivo

1. **Menos frases enlatadas.** MiniLM/spaCy **no** rutean el turno.
2. Skills claras siguen por **keyword** (sin LLM): juegos, cuento, música, yoga, abrazo, nombre, hambre/sed.
3. **Excepción padres:** regex actual de “llama / hablar con mamá o papá” → `call_parent`, TTS enlatado, **notificación a la app**. El LLM no interviene en ese turno.
4. **Todo lo demás** (incluye `zanahoria`, `hola`, `me duele`, `quiero a mama` sin “llama”) → `unknown` → LLM. El modelo responde o pone `[NOTIFY_PARENT:…]` si pide un grande o hay crisis/dolor/miedo real. Sin tag, no hay aviso.

## Fuera de alcance

- Reescribir o borrar `intent_rules.json` (las entradas sin keyword quedan muertas; no hace falta limpiarlas en v1).
- Fine-tune, cambiar modelo GGUF, Groq vs local.
- Nuevas regex de dolor/crisis (`me duele`, `quiero a mama`). Eso lo decide el LLM.
- Cambiar FCM/pairing/GPIO.
- Companion visual / UI Android.
- Mute `[INTENTS_OFF]` / failsafe: se mantiene el spec `2026-08-28-intent-mute-llm-design.md`.

## Comportamiento

### Orden de un turno (mute OFF)

1. STT + saneo, igual que hoy.
2. `IntentDispatcher.dispatch(text)`:
   - Texto vacío → `unknown`, conf 0.
   - `is_clear_keyword_intent(text)` no nulo y el nombre existe en `intent_rules.json` → ese intent, confianza `max(0.92, …)` no aplica embeddings: **fijo 0.92**, respuesta enlatada de ese intent.
   - Si no → `unknown`, conf 0, respuesta vacía.
3. Motores (juego / cuento / yoga) si el intent los arranca, igual que hoy.
4. LLM si el intent está en `_LLM_INTENTS` (`unknown`, `question_curiosity`, `help_request`) y no hay motor activo. Tras este cambio, charla cae en `unknown`; `question_curiosity` / `help_request` **dejan de dispararse** (no hay keyword). El LLM cubre esas frases.
5. Si `intent_name == "call_parent"`: `push_notification` de pedido a mamá/papá (código actual, paso 11.5).
6. Tags del LLM: `[NOTIFY_PARENT]` avisa y fuerza intents ON (`reason=notify_parent`). Sin tag, no avisa.

### Keywords que siguen enlatadas

Solo las de `is_clear_keyword_intent` en `session_policy.py` (no ampliar en v1):

| Keyword | Intent |
|---|---|
| veo veo | `play_veo_veo` |
| piedra/papel/tijera | `play_piedra_papel` |
| cuento / contame un cuento | `story_request` |
| canción / música / cantame | `song_request` |
| parar música | `stop_music_request` |
| yoga / estirarme / quiero moverme | `yoga_request` |
| abrazo | `hug_request` |
| cómo te llamás / quién sos / tu nombre | `identity_name` |
| tengo hambre/sed, quiero agua/comer | `needs_basic` |
| llama/llamar/avisale + mamá/papá; quiero hablar con mamá/papá | `call_parent` |

El orden de las regex **no cambia**: `identity_name` se evalúa **antes** que `call_parent`, así “cómo te llamás” no avisa al padre.

“quiero a mamá” **no** es `call_parent`. Va al LLM; el modelo puede avisar o solo acompañar.

### Mute ON

Igual que hoy: no se llama a `dispatch`, salvo keyword de veo veo / PPT (prende intents y arranca el motor). Yoga, abrazo y llama-a-mamá **siguen sin** keyword mientras está OFF; el LLM puede `[NOTIFY_PARENT]` + `[INTENTS_ON]`.

### Prompt

Mismo `_SYSTEM_PROMPT` para local y Groq. Añadir reglas normativas:

- Usá `[NOTIFY_PARENT:razón breve]` **solo** si el nene pide hablar con mamá/papá, o describe crisis, dolor fuerte o miedo de verdad.
- **No** avises por una palabra suelta, un color, un juego, una verdura, un bicho o charla de jardín.
- Si no hay pedido ni crisis: respondé corto, **sin** el tag.

Mantener las reglas ya existentes de tags, juegos reales e `[INTENTS_ON]` si avisás.

### MiniLM / spaCy

No se usan para rutar. En v1: **no cargar** `SentenceTransformer` en `IntentDispatcher` y **no** llamar `_score_intents` / encode por turno. Ahorra RAM y CPU en la Pi. spaCy puede seguir cargándose si otro código del proceso lo necesita; `dispatch` no puntúa similitud.

Dejar los métodos de overlap/thin en el archivo no es obligatorio; `dispatch` no debe depender de ellos para elegir intent.

### Logs

`INTENT_DISPATCH` sigue logueando input/output. Si es keyword: `intent=… conf=0.920`. Si no: `unknown` (o el texto de rechazo actual equivalente). No hace falta loguear scores MiniLM.

## Unidades

### `IntentDispatcher.dispatch` (`workers.py`)

Unidad de ruteo: keyword o unknown. No embeddings.

### `is_clear_keyword_intent` (`session_policy.py`)

Sin cambios de regex en v1, salvo bug demostrado (p. ej. “cómo te llamás” → `call_parent`). Los tests actuales de `test_session_policy.py` deben seguir pasando.

### `AudioWorker` notify

Sin cambio de contrato: notifica en `call_parent` y en tag `[NOTIFY_PARENT]`. No notificar en `body_hurt` / `crisis_cry` enlatados (esos intents ya no se eligen).

### Prompt (`fallback_llm.py`)

Texto; tests de substring.

## Tests (TDD, sin GGUF)

Extender `test_session_policy.py` / tests del dispatcher (mock cv2 como `test_intent_accuracy.py`):

1. `"Zanahoria."` → `unknown`.
2. `"Encontré un bichito en el jardín."` → `unknown`.
3. `"hola"` → `unknown`.
4. `"me duele la panza"` → `unknown`.
5. `"quiero a mama"` → `unknown` (no `crisis_cry` ni `call_parent`).
6. `"llama a mama"` → `call_parent`.
7. `"quiero hablar con papa"` → `call_parent`.
8. `"como te llamas"` → `identity_name`, **no** `call_parent`.
9. `"juguemos veo veo"` → `play_veo_veo`.
10. `_SYSTEM_PROMPT` incluye “no avises” / palabra suelta o equivalente explícito, y sigue pidiendo `[NOTIFY_PARENT]` cuando sí corresponde.

Actualizar `test_intent_accuracy.py`: los casos que no son keyword esperan `unknown`; los keyword siguen al intent de la tabla de arriba. Accuracy deja de medir MiniLM.

`test_intent_mute.py` y `test_session_policy.py` (mute, barge-in, keyword padres) no se relajan.

## Criterio de hecho

- “Zanahoria” no habla de mamá/papá ni de dolor enlatado; va al LLM.
- “Llama a mamá” avisa a la app y usa copy de `call_parent`.
- “Cómo te llamás” sigue siendo TEO, no aviso al padre.
- Un turno sin keyword no elige `body_hurt`, `crisis_cry`, `school_day` ni `birthday_talk` por similitud.
- Pi: no carga MiniLM al iniciar el dispatcher.
