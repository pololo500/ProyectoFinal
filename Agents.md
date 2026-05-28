# Contexto del Proyecto: Sistema Edge AI Interactivo
Este proyecto es el "cerebro" local para un sistema embebido interactivo. Todo el procesamiento debe ocurrir localmente optimizando el uso de CPU y RAM, aplicando principios de Edge Computing.

## Stack Tecnológico Obligatorio
- **Video:** `opencv-python` (captura) y `mediapipe` (detección facial y emociones).
- **Audio (Captura):** `sounddevice` (I/O) y `silero-vad` (detección de silencios y actividad de voz).
- **Audio (Procesamiento):** `faster-whisper` (transcripción STT rápida).
- **Procesamiento de Lenguaje (NLU):** `spacy` (modelo `es_core_news_sm` para similitud semántica).
- **Saneamiento de Datos:** `scrubadub` (eliminación de PII).
- **Interfaz (Solo para PoC):** `tkinter` o `PyQt` (a elección del agente para la prueba de concepto).

## Reglas Arquitectónicas y de Código
1. **Multithreading Estricto:** La interfaz gráfica (UI) no debe bloquearse. La lectura de la cámara, el streaming del micrófono y la inferencia de los modelos (Whisper/MediaPipe) deben ejecutarse en hilos (threads) o procesos separados, comunicándose mediante Colas (`queue.Queue`).
2. **Patrón de Enrutamiento:** No utilizar cadenas de `if/else` para evaluar qué dijo el usuario. Implementar un "Despacho por Diccionario" (Dictionary Dispatch) donde un JSON define Intenciones -> Respuestas, evaluadas mediante la similitud semántica de spaCy.
3. **Regla Crítica de Privacidad y Fidelidad de Datos:** Al utilizar la librería para sanear los datos sensibles transcritos, está ESTRICTAMENTE PROHIBIDO generar placeholders de texto por defecto (ej. "[NAME]" o "[REDACTED]"). La lógica de extracción debe forzar la inserción del valor `null` explícitamente en las estructuras de datos o JSON resultantes donde la información fue omitida, garantizando la fidelidad de los datos para el procesamiento posterior.
4. **Manejo de Silencios:** El micrófono debe grabar en un buffer circular. La grabación de un segmento se corta y se envía a `faster-whisper` solo cuando `silero-vad` detecta un silencio continuo de aproximadamente 2.5 segundos.