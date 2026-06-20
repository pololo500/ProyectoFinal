# Contexto del Proyecto: Sistema Edge AI Interactivo
Este proyecto es el "cerebro" local para un sistema embebido interactivo. Todo el procesamiento debe ocurrir localmente optimizando el uso de CPU y RAM, aplicando principios de Edge Computing.

## Plataforma Objetivo
- **Desarrollo:** Windows 10/11 (x86_64).
- **Producción:** Raspberry Pi 5 (ARM64 Cortex-A76 @ 2.4GHz, 4-8GB RAM, sin GPU dedicada).
- El código debe ser compatible con ambas plataformas sin modificaciones manuales.

## Stack Tecnológico Obligatorio
- **Video:** `opencv-python` (captura a 640×480, 3fps) y `mediapipe` (detección facial y emociones vía blendshapes).
- **Audio (Captura):** `sounddevice` (I/O) y `silero-vad` (detección de silencios y actividad de voz).
- **Audio (Procesamiento):** `faster-whisper` (transcripción STT, modelo `base` con `compute_type="int8"`, `beam_size=5`, `initial_prompt` contextual para habla infantil argentina).
- **Audio (Síntesis/TTS):** `piper-tts` (TTS neural local con voz lo más humana posible, modelo `es_MX-ald-medium`). Si piper no está disponible, fallback a `System.Speech` (Windows) o `espeak-ng` (Linux).
- **Procesamiento de Lenguaje (NLU):** `spacy` (modelo `es_core_news_sm` para similitud semántica, docs de ejemplos pre-cacheados).
- **Saneamiento de Datos:** `scrubadub` (eliminación de PII).
- **Interfaz (Solo para PoC):** `tkinter` o `PyQt` (a elección del agente para la prueba de concepto).

## Reglas Arquitectónicas y de Código
1. **Multithreading Estricto:** La interfaz gráfica (UI) no debe bloquearse. La lectura de la cámara, el streaming del micrófono y la inferencia de los modelos (Whisper/MediaPipe) deben ejecutarse en hilos (threads) o procesos separados, comunicándose mediante Colas (`queue.Queue`).
2. **Patrón de Enrutamiento:** No utilizar cadenas de `if/else` para evaluar qué dijo el usuario. Implementar un "Despacho por Diccionario" (Dictionary Dispatch) donde un JSON define Intenciones -> Respuestas, evaluadas mediante la similitud semántica de spaCy.
3. **Regla Crítica de Privacidad y Fidelidad de Datos:** Al utilizar la librería para sanear los datos sensibles transcritos, está ESTRICTAMENTE PROHIBIDO generar placeholders de texto por defecto (ej. "[NAME]" o "[REDACTED]"). La lógica de extracción debe forzar la inserción del valor `null` explícitamente en las estructuras de datos o JSON resultantes donde la información fue omitida, garantizando la fidelidad de los datos para el procesamiento posterior.
4. **Manejo de Silencios:** El micrófono debe grabar en un buffer circular. La grabación de un segmento se corta y se envía a `faster-whisper` solo cuando `silero-vad` detecta un silencio continuo de aproximadamente 1.8 segundos (ajustado para utterances cortos de niños de 2-4 años).
5. **Carga Secuencial de Modelos:** Los modelos pesados (MediaPipe, Whisper, piper) deben cargarse secuencialmente, no en paralelo, para evitar contención de CPU. El AudioWorker espera al evento `models_loaded_event` del CameraWorker antes de cargar Whisper.
6. **Mensajes Críticos No Descartables:** Los mensajes de tipo `transcript` deben usar `put(timeout=...)` en la cola (nunca `put_nowait`) para garantizar que jamás se pierdan silenciosamente.
7. **TTS con Voz Natural:** La respuesta de la intención detectada debe reproducirse por el parlante seleccionado con la voz más humana posible, priorizando `piper-tts` neural. El consumo de recursos debe ser mínimo (modelo ONNX optimizado para ARM64).