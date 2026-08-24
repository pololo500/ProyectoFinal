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
