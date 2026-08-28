# Mute de intents tras pregunta del LLM — diseño

Fecha: 2026-08-28  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

Cuando el LLM pregunta algo y espera respuesta, el turno siguiente del nene sigue pasando por los 39 intents. Un “sí”, un color o una frase corta puede disparar enojo, veo veo u otra skill y marear al nene.

Además el LLM y el copy enlatado de `play_generic` / `activity_offer` a veces ofrecen juegos que **no existen** en el robot.

## Objetivo

1. El LLM puede **apagar y prender** el despacho de intents con tags, igual que `[PLAY_MUSIC]` o `[NOTIFY_PARENT]`.
2. Con intents apagados, la frase va al LLM, **salvo** keyword clara de **veo veo** o **piedra-papel-tijera**: ahí arranca el `GameEngine` en el mismo turno y se prenden los intents.
3. Si el nene pide jugar (sin elegir motor), TEO ofrece **solo** esos dos juegos y puede mencionar música o un cuento. No inventa otros.
4. Cada **cambio** de estado ON/OFF se escribe en los logs de debug.

## Fuera de alcance

- Barge-in / mic durante TTS.
- Tool-calling JSON.
- GPIO, FCM, pairing.
- Que yoga, abrazo o “llama a mamá” arranquen por keyword mientras está OFF. Esos casos los ve el LLM (`[NOTIFY_PARENT:…]` + `[INTENTS_ON]`).

## Comportamiento

### Tags

Al final de la respuesta del LLM, **no se dicen en voz alta**:

| Tag | Efecto |
|---|---|
| `[INTENTS_OFF]` | Apaga el `IntentDispatcher` para los próximos turnos del nene. |
| `[INTENTS_ON]` | Lo vuelve a prender. |

Pueden convivir con `[NOTIFY_PARENT:…]`. Si en la misma respuesta aparecen OFF y ON, **gana el último** en el texto.

El TTS sigue usando `_strip_unspeakable`: estos tags no se leen.

### Prompt (local y Groq: el mismo `_SYSTEM_PROMPT`)

Texto normativo, no opcional:

- Si preguntás algo y esperás que el nene conteste, poné `[INTENTS_OFF]` en esa respuesta.
- Cuando **terminaste de preguntar**, poné `[INTENTS_ON]` **en esa misma respuesta**. No dejes OFF “por las dudas”.
- Si el nene pide a mamá/papá: `[NOTIFY_PARENT:razón]` **y** `[INTENTS_ON]`.
- No juegues vos al veo veo ni al piedra-papel-tijera.
- Si pide jugar: ofrecé **solo veo veo y piedra papel o tijera**. Podés mencionar música o un cuento. Prohibido inventar otros juegos (escondidas, memoria, “inventamos uno”, etc.).

### Orden de un turno con mute ON (intents apagados)

1. STT + saneo como hoy.
2. Si `is_clear_keyword_intent` es `play_veo_veo` o `play_piedra_papel`:  
   `set_on(reason="game_keyword")` → `game_engine.process_or_passthrough` / `start_game` **sin LLM**.
3. Si no: **no** llamar a `IntentDispatcher.dispatch`. Tratar como `unknown` y generar con LLM.
4. Parsear tags de la respuesta. Aplicar OFF/ON. Si hay `[NOTIFY_PARENT:…]`, forzar ON con `reason="notify_parent"` aunque el modelo se olvide `[INTENTS_ON]`.
5. Si el turno termina **sigue** muteado, incrementar el contador de turnos muteados.

Con mute OFF: flujo actual (dispatcher → juegos/yoga/cuento → LLM solo en `unknown` / `question_curiosity` / `help_request`).

### Failsafe

Si el modelo deja OFF y nunca pone ON: al **cerrar el tercer turno** del nene todavía muteado, forzar ON con `reason="failsafe"`. El **cuarto** turno del nene ya pasa por intents. No desmutear *antes* de que el LLM conteste el tercer turno: un “sí” no debe caer en `emotion_angry`.

Un `[INTENTS_ON]`, un keyword de juego o un `NOTIFY_PARENT` reinician el contador a 0.

### Logs

Solo cuando el flag **cambia**. Canal: `log_action("INTENTS", ...)` y, si `--debug`, `log_output("INTENTS", ...)`.

Formato de mensaje:

`off→on reason=game_keyword text="juguemos veo veo"`  
o `on→off reason=llm_tag text="…"`  

`reason` ∈ `llm_tag` | `game_keyword` | `failsafe` | `notify_parent`.

`text` es la frase del nene recortada (~80 caracteres). Si no hay frase (tag en vacío), omitir `text`.

Si el LLM emite `[INTENTS_OFF]` y ya estaba OFF: no loguear.

### Copy enlatada

`play_generic` y `activity_offer` en `intent_rules.json`: ninguna frase ofrece un juego que no sea veo veo o piedra-papel-tijera, ni “inventamos uno”, ni “inventar un juego”. Música y cuento sí se pueden mencionar.

## Unidades

### `IntentMute` (`session_policy.py`)

Un objeto de sesión, no global de proceso más que el que vive en `AudioWorker`.

- `is_muted: bool`
- `turns_while_muted: int`
- `apply_tag(on: bool, reason: str, child_text: str) -> bool` — aplica si el estado cambia; si cambió, loguea y retorna True.
- `note_game_keyword(child_text: str) -> None` — ON + reason `game_keyword`.
- `note_child_turn_still_muted() -> None` — incrementa; si llega a 3, ON + `failsafe`.
- `reset()` — ON, contador 0; log solo si el flag cambia.

Helpers puros (fáciles de testear, sin I/O):

- `should_run_intent_dispatcher(muted: bool) -> bool` — `False` si muteado.
- `game_keyword_while_muted(muted: bool, keyword: str | None) -> str | None` — devuelve `play_veo_veo` o `play_piedra_papel` solo si muteado y el keyword es uno de esos dos; si no, `None`.

`workers.py` usa esos helpers: mute + juego → motor; mute + resto → LLM; no mute → dispatcher.

### Parser de tags (`workers.py`)

Extender `_ACTION_TAG_RE` con `INTENTS_OFF` e `INTENTS_ON`. En `_execute_actions`: esos dos no hablan ni tocan música; solo llaman a `IntentMute`.

### Prompt y cloud

Un solo `_SYSTEM_PROMPT` en `fallback_llm.py` (Groq ya lo importa). Tests de string sobre ese texto.

## Tests (TDD, sin modelo GGUF)

Archivo nuevo `test_intent_mute.py` (y asserts extra en `test_llm_story_guard.py` / copy JSON):

1. `should_run_intent_dispatcher(True)` es False; con False, True. `game_keyword_while_muted(True, "play_veo_veo")` es el juego; `game_keyword_while_muted(True, "emotion_angry")` es None.
2. OFF + `note_game_keyword("juguemos veo veo")` deja `is_muted is False`.
3. OFF + keyword PPT → igual.
4. `apply_tag(False)` luego `apply_tag(False)`: un solo log (mock de `log_action`).
5. Tres `note_child_turn_still_muted` → `is_muted is False` y un log `failsafe`.
6. `_SYSTEM_PROMPT` contiene `INTENTS_OFF`, `INTENTS_ON`, “veo veo” y “piedra”.
7. Ninguna `response` de `play_generic` / `activity_offer` contiene “inventamos” ni “inventar un juego”.

El arranque real del `GameEngine` en el worker se cubre con un test de `process_or_passthrough` ya existente más el flag ON; no hace falta levantar Whisper.

## Criterio de hecho

- Pregunta del LLM + OFF: la respuesta corta del nene no dispara un intent enlatado.
- “Veo veo” / PPT en ese modo: motor de juego, no charla LLM.
- Logs de debug muestran el cambio de flag con motivo.
- Pedir jugar no ofrece juegos inventados.
