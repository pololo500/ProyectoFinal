# Latencia audio/cámara — qué cambió y cómo volver atrás

Cambios del 24/08/2026. Todo está en `workers.py` salvo que se indique otra cosa.
Si un cambio fue un error de concepto, revertí **solo ese punto** (valores anteriores entre paréntesis).

## Hecho ahora

### 1. Silencio más corto
- `EmotionReactor.NORMAL_SILENCE`: **0.7 s** (antes **1.2**)
- `EmotionReactor.EXTENDED_SILENCE`: **1.6 s** (antes **3.0**) — triste/enojado
- **Síntoma si está mal:** corta “quiero… música” a mitad.
- **Revertir:** 1.2 y 3.0.

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
- `AudioWorker.MAX_LISTEN_SECONDS`: **8.0** (antes **15.0**)
- **Síntoma si está mal:** corta un cuento largo.
- **Revertir:** 15.0.

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
