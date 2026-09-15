# Filtro de habla débil + confianza Whisper — diseño

Fecha: 2026-09-15  
Producto: peluche TEO (`ProyectoParaRasperrypiV5` + `ServidorDePC`)  
Estado: aprobado en conversación (puntos 2 y 3); silencio al descartar

## Problema

Clips de ~2 s transcritos como «qué pasa» / «qué es eso» tienen 1–4 % de hops ≥ 7 % (19–99 ms de energía). El VAD arranca con un hop y el hangover rellena silencio. Whisper alucina. El STT de la PC no devuelve `no_speech_prob` / `avg_logprob`, así que el gate de confianza local no corre.

## Comportamiento

1. **Antes del STT:** si `active_speech_seconds` (hops 20 ms, piso `LISTEN_VOLUME_FLOOR_PCT = 7`) es **&lt; 0,30 s**, no Whisper, no LLM, no TTS. Log `[STT] ruido, sin transcribir`. El mic sigue.
2. **Después del STT (Pi o PC):** si hay texto y `avg_logprob < -0,9` o `no_speech_prob > 0,75`, mismo silencio (no «No te escuché», no LLM).
3. Fuera de alcance: denylist de frases, cambiar el piso 7 %, AEC.

## Unidades

- `session_policy.skip_stt_for_weak_speech(active_s) -> bool`
- `session_policy.stt_is_low_confidence(text, avg_logprob, no_speech_prob) -> bool`
- `workers.active_speech_seconds(pcm, sample_rate=16000) -> float`
- `ServidorDePC` JSON STT: `text`, opcional `avg_logprob`, `no_speech_prob`
