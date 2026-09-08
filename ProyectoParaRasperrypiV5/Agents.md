# Contexto del Proyecto: Sistema Edge AI Interactivo
Este proyecto es el "cerebro" local para un sistema embebido interactivo. Todo el procesamiento debe ocurrir localmente optimizando el uso de CPU y RAM, aplicando principios de Edge Computing.

## Plataforma Objetivo
- **Desarrollo:** Windows 10/11 (x86_64).
- **Producción:** Raspberry Pi 5 de 8GB (ARM64 Cortex-A76 @ 2.4GHz, 8GB RAM, sin GPU dedicada).
- El código debe ser compatible con ambas plataformas sin modificaciones manuales.

## Stack Tecnológico Obligatorio
- **Video:** `opencv-python` (captura a 320×240, 1 fps; MediaPipe de emoción apagado por defecto) y `mediapipe` (opcional si `infer_emotion=True`).
- **Audio (Captura):** Linux (Pi 5): `arecord` persistente `-D hw:CARD=…,DEV=0 -t raw -f S16_LE -c 1 -r 48000` (override `ALSA_CAPTURE_DEVICE`). El hilo drain no se detiene en TTS/Whisper/LLM; mute = no encolar al VAD. Downsample 48→16 (promedio de 3) fuera del drain. Windows: `sounddevice` InputStream a 16 kHz. Playback (otra tarjeta): `sounddevice` OutputStream. En la Pi 5 el VAD es energía RMS (Silero no se carga en aarch64: Bus error). En Windows, `silero-vad` si está disponible.
- **Audio (Procesamiento):** `faster-whisper` (transcripción STT, modelo `medium` con `compute_type="int8"`, `beam_size=1`, `initial_prompt` contextual. Overrides: `WHISPER_MODEL=small`, rollback STT `WHISPER_BEAM=5`).
- **LLM de Fallback:** `llama-cpp-python` con Llama 3.2 3B Instruct Q4_K_M por defecto (`LLM_PROFILE=3b`). El 1B se probó y se descartó por calidad. Opcional: `LLM_PROFILE=8b` (Llama 3.1 8B) o `LLM_PROFILE=1b`. Contexto `n_ctx=2048` (`llm_n_ctx()`; no usar 1024: el prompt no entra). Historial de **4 turnos** (rollback `CONVO_MAX_TURNS=10`). Override de modelo: `LLM_HF_REPO` + `LLM_GGUF`.
- **Audio (Síntesis/TTS):** `piper-tts` (TTS neural local, modelo `es_AR-daniela-high`, `length_scale=1.20`, `noise_scale=0.667`, `noise_w_scale=0.98`). Si piper no está disponible, fallback a `System.Speech` (Windows) o `espeak-ng` (Linux).
  - Ritmo: `length_scale` más alto = más lento. Valor actual 1.20 (pausado, cadencia menos imperativa). Si no convence, siguiente paso documentado: **1.30** (más lento y marcado; puede arrastrar sílabas). Constantes en `SpeechWorker` (`workers.py`).
- **Hardware (Pi 5):** pines BCM en `hardware_pins.json`. Pulsador GPIO 27 (pull-up interno) pide un abrazo. Servos SG90 GPIO 12 y 13. LCD ST7789V SPI0 CE0, DC GPIO 24, RST GPIO 25. En Windows se simula.
- **Procesamiento de Lenguaje (NLU):** ver regla 2 abajo. **Solo si hay match** de keyword se ejecuta un intent enlatado. **Sin match (`unknown`): SIEMPRE preguntar al LLM.** MiniLM no se carga. Keywords: saludo/despedida de frase entera, juegos, cuento, música, yoga, abrazo, nombre, hambre/sed, `call_parent`. Rollback de hola/chau: sacar `_GREETING_PHRASES` / `_FAREWELL_PHRASES`.
- **Saneamiento de Datos:** `scrubadub` (eliminación de PII).
- **Interfaz (Solo para PoC):** `tkinter` o `PyQt` (a elección del agente para la prueba de concepto).

## Reglas Arquitectónicas y de Código
1. **Multithreading Estricto:** La interfaz gráfica (UI) no debe bloquearse. La lectura de la cámara, el streaming del micrófono y la inferencia de los modelos (Whisper/MediaPipe) deben ejecutarse en hilos (threads) o procesos separados, comunicándose mediante Colas (`queue.Queue`).
2. **Ruteo NLU (obligatorio — no negociable):**
   - **Solo si hay match** de keyword (`session_policy.is_clear_keyword_intent`) se ejecuta la **respuesta enlatada** de ese intent (`intent_rules.json`). En ese turno **no** se llama al LLM.
   - **Sin match (`unknown`): SIEMPRE preguntar al LLM** qué responder. No elegir intent por similitud spaCy/MiniLM. No hablar una entrada de `intent_rules.json` como si fuera un intent.
   - No es “unknown charla” (el LLM no aplica): un motor de juego/cuento/yoga **ya activo** en ese turno; mute `[INTENTS_OFF]`; noche o tope de playtime. Si el LLM no contestó (timeout/vacío), se permite **una** frase de último recurso; eso **no** es un intent.
3. **Regla Crítica de Privacidad y Fidelidad de Datos:** Al utilizar la librería para sanear los datos sensibles transcritos, está ESTRICTAMENTE PROHIBIDO generar placeholders de texto por defecto (ej. "[NAME]" o "[REDACTED]"). La lógica de extracción debe forzar la inserción del valor `null` explícitamente en las estructuras de datos o JSON resultantes donde la información fue omitida, garantizando la fidelidad de los datos para el procesamiento posterior.
4. **Manejo de Silencios:** El micrófono graba en un buffer circular. El segmento se corta y va a `faster-whisper` cuando ocurre lo primero de: (a) el VAD detecta ~1.2 s de silencio (3.0 s si hay emoción triste/enojado), o (b) la captura lleva 8 s. En Pi el log dice `energy-vad:` (no Silero). Huecos de cola no cuentan como silencio. Rollback 0.7/15 s: `docs/LATENCIA_AUDIO_CAMARA.md`.
5. **Carga Secuencial de Modelos:** Los modelos pesados (MediaPipe, Whisper, piper) deben cargarse secuencialmente, no en paralelo, para evitar contención de CPU. El AudioWorker espera al evento `models_loaded_event` del CameraWorker antes de cargar Whisper. Tras `fallback_llm.load()`, `warmup()` (generate corto, `history=[]`, **sin TTS**) antes de abrir el mic: el primer decode de llama-cpp tarda 2–3×.
6. **Mensajes Críticos No Descartables:** Los mensajes de tipo `transcript` deben usar `put(timeout=...)` en la cola (nunca `put_nowait`) para garantizar que jamás se pierdan silenciosamente.
7. **TTS con Voz Natural:** La respuesta de la intención detectada debe reproducirse por el parlante seleccionado con Piper `es_AR-daniela-high`. El consumo de recursos debe ser mínimo (modelo ONNX optimizado para ARM64).