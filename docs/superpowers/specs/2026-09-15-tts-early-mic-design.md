# Micrófono 0,2 s antes de que termine el TTS — diseño

Fecha: 2026-09-15  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación (opción A); sin commit hasta que Teo lo pida

## Problema

Hoy el micrófono es half-duplex estricto:

1. Cerrado **todo** el rato que el parlante suena (`is_busy()` / `_speaker_busy()`).
2. Tras el TTS, `_silence_mic_after_speaker` vacía la cola y deja el mic cerrado **0,40 s** (`ECHO_MUTE_SECONDS`).
3. El `finally` de `_handle_segment` vuelve a vaciar la cola.

Si el chico arranca a hablar en el último tramo de la frase de TEO, o en el instante en que termina, ese audio no existe.

## Objetivo

1. En una **respuesta hablada** (TTS conversacional), el micrófono empieza a encolar **0,20 s antes** de que el parlante deje de sonar.
2. Tras ese TTS: **no** vaciar esa cola y **echo mute = 0**.
3. Si el chico responde rápido, el próximo `listen_until_cut` ya tiene el arranque en la cola / pre-roll.

## Fuera de alcance (v1)

- Abrir el mic durante **música**.
- Abrir el mic durante **cuento** (`story=True`, `_story_pipeline_active`, `speak_sentences_and_wait`).
- Cancelación de eco / AEC / filtrar la cola de TEO en Whisper.
- Barge-in (cortar a TEO si el chico habla encima).
- Cambiar umbrales VAD, piso de volumen, o tope de captura.
- Abrir el mic durante Whisper / LLM (sigue muteado).

## Decisiones

- **Opción A:** overlap 0,20 s **y** se saca la cola de eco de 0,40 s **solo** después de TTS conversacional. El último tramo de TEO puede colarse al STT; se acepta.
- **Música y cuento:** igual que hoy (mic cerrado hasta el final + drain + `ECHO_MUTE_SECONDS = 0.40`).
- **Frase &lt; 0,20 s:** el mic se abre desde que **empieza** el playback (no desde que Piper sintetiza).
- **Mientras Piper sintetiza** (aún no hay audio en el parlante): el mic sigue cerrado. Duración desconocida = bloquea.
- **`is_busy()` no cambia:** sigue `True` hasta el último sample (UI, hug, interrupciones). El mic usa otra predicado: `tts_blocks_mic`.
- **Mute STT/LLM vs TTS:** `set_muted(True)` cubre Whisper/LLM. Antes de `speak_and_wait` conversacional se hace `set_muted(False)`; quien cierra el mic en esa fase es `tts_blocks_mic`, no el flag muted.

## Comportamiento

```
Whisper / LLM          mic muted, cola drain (como hoy)
Piper sintetiza        mic cerrado (tts_blocks_mic True, remaining desconocido)
Playback TTS           mic cerrado mientras remaining > 0.20 s
Últimos 0.20 s TTS     mic abierto, encola al VAD
TTS termina            no drain, echo_until = now (cola de 0)
listen_until_cut       consume la cola (pre-roll / voz del chico)
```

Música / cuento: `tts_blocks_mic` es `True` mientras haya playback; después `_silence_mic_after_speaker` con 0,40 s.

## Arquitectura

```
SpeechWorker
  al arrancar OutputStream: guarda playback_end = now + n_samples / sr
  remaining = max(0, playback_end - now)
  tts_blocks_mic()  →  session_policy.tts_blocks_mic(remaining, music, story)

AudioWorker / AlsaCapture / callback Windows
  _speaker_busy() usa tts_blocks_mic(), no is_busy()
  listen_until_cut: mic_open_for_listen(speaker_playing=tts_blocks_mic(), ...)

Tras speak_and_wait conversacional
  no llamar drain
  _echo_mute_until = 0  (o now, para que now >= echo_until)
Tras play_audio_file / cuento
  _silence_mic_after_speaker como hoy
```

`finally` de `_handle_segment`: no vaciar la cola si acaba de haber TTS conversacional con overlap. Sí vaciar si el turno no habló, o si siguió música/cuento.

## Unidades

### `tts_blocks_mic` (`session_policy.py`)

| | |
|---|---|
| Hace | `True` si el mic no debe encolar por el parlante |
| Uso | `tts_blocks_mic(remaining_s, is_music, is_story)` |
| Depende | constantes; sin OpenCV ni ALSA |

Reglas:

- `is_music` o `is_story`: `True` si `remaining_s` es `None` o `> 0`.
- TTS conversacional: `True` si `remaining_s` es `None` o `> MIC_EARLY_OPEN_SECONDS` (`0.20`).
- `remaining_s == 0`: `False` (ya no hay audio).

### `SpeechWorker` (`workers.py`)

| | |
|---|---|
| Hace | Expone remaining de **este** playback y `tts_blocks_mic()` |
| Uso | AudioWorker / AlsaCapture `speaker_busy` |
| Depende | `session_policy.tts_blocks_mic` |

Al iniciar el stream de TTS (no música): `_tts_playback_end = monotonic() + duration`. Al terminar o al interrupt: remaining 0 / end en el pasado. Música y pipeline de cuento reportan bloqueo total (`is_music` / `is_story`).

### Captura (`alsa_capture.py`, callback Windows, `listen_until_cut`)

Siguen preguntando “¿el parlante bloquea el mic?”. Esa respuesta pasa a ser `tts_blocks_mic()`, no `is_busy()`.

## Error handling

- Interrupt / hug / `stop_event` a mitad de frase: `playback_end` se invalida; el mic no queda abierto “de a 0,2 s” sobre audio que ya no suena.
- `speak_and_wait` timeout: igual; idle se setea y remaining cae a 0.
- Si no se pudo abrir OutputStream: no hay playback_end; el mic no se abre por overlap (no había cola de parlante).

## Testing

Puro, sin hardware:

- `tts_blocks_mic(None, False, False)` → `True` (sintetizando).
- `tts_blocks_mic(0.21, False, False)` → `True`.
- `tts_blocks_mic(0.20, False, False)` → `False` (abre en `<= 0.20`).
- `tts_blocks_mic(0.10, False, False)` → `False`.
- `tts_blocks_mic(0.10, True, False)` → `True` (música).
- `tts_blocks_mic(0.10, False, True)` → `True` (cuento).
- Tras TTS conversacional, el código de `_handle_segment` **no** drena la cola (test de fuente o helper).
- `_silence_mic_after_speaker` sigue existiendo para música.

## Rollback

Sacar `tts_blocks_mic` y volver `_speaker_busy` a `is_busy()`, restaurar drain + `ECHO_MUTE_SECONDS` después de todo `speak_and_wait`.
