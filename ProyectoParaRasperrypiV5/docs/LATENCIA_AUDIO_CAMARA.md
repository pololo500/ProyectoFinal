# Latencia audio/cámara — qué cambió y cómo volver atrás

Cambios del 24/08/2026. Todo está en `workers.py` salvo que se indique otra cosa.
Si un cambio fue un error de concepto, revertí **solo ese punto** (valores anteriores entre paréntesis).

## Hecho ahora

### 1. Silencio (frases cortadas)
- `EmotionReactor.NORMAL_SILENCE`: **1.2 s** (el **0.7** del 24/08 cortaba “quiero… música”)
- `EmotionReactor.EXTENDED_SILENCE`: **3.0 s** (triste/enojado; casi no aplica con emoción apagada)
- Log: `energy-vad:` en Pi (Silero no corre en aarch64).
- **Síntoma si 1.2 está mal:** el peluche tarda de más en “cerrar” el turno.
- **Revertir (latencia):** 0.7 y 1.6.

### 5. Hilos de Whisper
- `WhisperModel(..., cpu_threads=2)` (antes **4**)
- Pi 5 tiene 4 cores: 4 hilos de Whisper se pisaban con Piper. 2 deja aire al audio I/O.
- **Síntoma si está mal:** transcribe *más lento* con la cámara ya al mínimo.
- **Revertir:** `cpu_threads=4`.

### 6. Preproceso más flaco
- Filtro / resta espectral / gate / pre-énfasis: ya estaban comentados.
- Pad a 1.5 s: **desactivado** (la llamada a `_pad_audio` está comentada al final de `_preprocess_audio`).
- Sigue: quitar DC + normalizar.
- **Síntoma si está mal:** más alucinaciones en frases de 1 sílaba.
- **Revertir:** descomentar `audio = self._pad_audio(...)`.

### 7. Cámara al mínimo
- `frame_rate = 1` (antes **3**)
- Captura **320×240** (antes **640×480**)
- `infer_emotion = False`: no carga MediaPipe; solo preview.
- Sleep 0.05 s por vuelta (antes 0.005).
- **Síntoma si está mal:** no hay emoción en el dashboard (esperado). Silencio extendido casi no se dispara porque no hay label de emoción.
- **Revertir emoción:** `self.infer_emotion = True`, `frame_rate = 3`, 640×480.

### 10. Tope de escucha
- `AudioWorker.MAX_LISTEN_SECONDS`: **8.0** (el **15.0** dejaba turnos largos)
- **Síntoma si 8 está mal:** corta cuentos o frases largas a mitad.
- **Revertir (cuentos):** 15.0.

### 11. Cola USB y downsample (2026-09-08)
- Cola de captura `AUDIO_QUEUE_MAXSIZE = 128` (antes 32). `drop_hits` no loguea en el callback.
- Si hay drops con voz activa, el hangover de silencio se pone en 0 (hueco ≠ silencio).
- 48 kHz → 16 kHz: promedio de 3 samples (anti-alias). No resamplear en el callback.
- **Síntoma si la cola 128 está mal:** más RAM (~0.8 MB). Irrelevante.
- **Revertir:** maxsize 32, `except Full: pass`, `arr[::3]`.

### 12. arecord persistente (2026-09-08)

- Linux: ya no se abre `sd.InputStream` por cada frase. Un `arecord` a `hw:CARD=…,DEV=0` (no `plughw`, no WAV, no 16 kHz en hw) queda vivo todo el `AudioWorker`.
- Lectura: 1920 bytes (960 frames @ 48 kHz = 20 ms). VAD suma la duración real del bloque (no 0.128 s fijos). Pre-roll ~1 s = 50 bloques; circular ~6 s = 300 bloques.
- Mute durante Whisper/LLM/TTS: se sigue leyendo el pipe (si no, SIGPIPE). No se encola al VAD. Tras el segmento se drena la cola.
- Watchdog: EOF o proceso muerto → restart. Stderr cuenta `overrun` / `busy`. Sin `--fatal-errors`, sin `-q`.
- `pipesize` 1 MiB, fallback 64 KiB. Usuario `teo` en grupo audio. **Sin sudo.**
- Override: `ALSA_CAPTURE_DEVICE=hw:CARD=Device,DEV=0`.
- Pedido ALSA: `--period-time=20000 --buffer-time=500000`; el log muestra lo negociado.
- **Síntoma si hw: está busy:** arecord stderr `Device or resource busy`. **No asumir PipeWire.** Primero: `lsof /dev/snd/pcmC*D0c` (y `fuser` si hace falta). Si el proceso es `pipewire` / `wireplumber` / `pipewire-pulse`, mask **manual** (no desde `app.py`):

      systemctl --user status pipewire wireplumber pipewire-pulse
      # solo si lsof confirmó que son ellos quienes tienen el PCM de captura:
      systemctl --user mask --now pipewire.socket pipewire.service wireplumber.service pipewire-pulse.service

  Rollback: `systemctl --user unmask …` y volver a arrancar. El parlante puede ser otra tarjeta; no maskear a ciegas.
- **No v1:** soxr, `nice -10`, pyalsaaudio, udev, `--fatal-errors`.
- **No usar como fix:** tuning USB OTG del kernel, variable PulseAudio plug-hw, forzar 16 kHz en `hw:`.
- Playback sigue en `sounddevice` OutputStream.
- **Revertir:** volver a `with sd.InputStream` por utterance en `workers.py` y borrar `alsa_capture.py`.

### 13. Warmup LLM (2026-09-08)
- Tras `load()` y **antes** de `arecord` / `InputStream`, `FallbackLLM.warmup()`: un `generate("ok", history=[])` cuya respuesta **no** va a Piper ni a `conversation_memory`.
- El primer decode de llama-cpp tarda 2–3×; así el primer turno del nene no paga ese costo.
- Ojos en `"zzz"` durante carga y warmup; `"escuchando"` después.
- **Revertir:** sacar `warmup()` en `workers.py` / `fallback_llm.py`.

## No implementado (acordado)

### 2. Standby — no bloquear el mic mientras Piper habla
Hoy `speak_and_wait` deja el mic muerto hasta que TEO termina la frase.
Más adelante: sintetizar/reproducir sin frenar la escucha (con cuidado de no pisar al nene).
**Recordatorio para Teo.**

### 3. Respuestas más cortas
No. Ya están bien.

### 4. Bajar Whisper `small` → `base`/`tiny`
No. El STT ya está al límite de calidad.

### 8. STT en la nube
No. Preferimos local.

### 9. Standby — si el keyword ya es claro, no esperar un Whisper “perfecto”
Ej.: `piedra papel`, `para la música` podrían despacharse apenas hay texto usable.
**Recordatorio para Teo.**

## 2026-08-30 — Silencio hasta la primera voz (opción A)

El silencio molesto era Whisper + LLM (hola/chau iban al modelo). Whisper sigue **`medium`**.
Detalle: `docs/superpowers/specs/2026-08-30-latencia-silencio-pre-tts-design.md`.

### Palancas (revertí **solo** la que falle)

| Palanca | Valor nuevo | Valor anterior | Síntoma si está mal | Cómo volver |
|---|---|---|---|---|
| `beam_size` Whisper | 1 (`whisper_beam_size()`) | 5 | Más alucinaciones STT, frases cortas mal | `WHISPER_BEAM=5` |
| Modelo Whisper | `medium` | `medium` | — | No se toca |
| `n_ctx` LLM | **2048** (`llm_n_ctx()`, default) | 1024 rompió el prompt (2026-08-30) | `Requested tokens … exceed context window of 1024` → frases enlatadas `unknown_fallback` | no bajar a 1024; default ya es 2048 |
| Turnos de memoria | 4 | 10 | No recuerda lo de hace rato | `CONVO_MAX_TURNS=10` |
| Keywords hola/chau | frase **entera** → `greeting`/`farewell` | iban al LLM | “hola me llamo Tomás” tratado como saludo (no debería) | sacar `_GREETING_PHRASES` / `_FAREWELL_PHRASES` en `session_policy.py` |
| Prompt | texto Teo 2026-08-30 | `al PPT.`, `[NOTIFY_PARENT:razón]`, CALM solo sueño/cansado | Tags raros / deja de avisar / no calma | restaurar copy anterior (abajo) |

Deshacer **todo** A sin tocar keywords/prompt:

`WHISPER_BEAM=5 CONVO_MAX_TURNS=10`

`n_ctx` se dejó en **2048**: con 1024 el system prompt no entra (`Requested tokens exceed context window`) y salen las frases enlatadas de `unknown_fallback`.

**No en v1:** streaming LLM→Piper (empezar a hablar en la primera oración). Más difícil de rollback.

**CALM_MODE al despedirse:** el prompt lo pide, pero `chau` / `me voy` **exactos** no pasan por el LLM (van enlatados). CALM aplica a despedidas más largas que sí van al modelo (p. ej. “chau, me voy a dormir”).

### Prompt — diff de copy (rollback)

Antes:

- `SIN jugar vos al PPT.`
- `[NOTIFY_PARENT:razón]`
- `[CALM_MODE]` si tiene sueño o está muy cansado.

Ahora (producción):

- `SIN jugar vos al Piedra Papel o Tijera.`
- `[NOTIFY_PARENT:razón explicandole al padre]`
- `[CALM_MODE]` si tiene sueño, está muy cansado o si el nene se despide.
