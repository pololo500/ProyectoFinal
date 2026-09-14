# Servidor PC: TTS Chatterbox rioplatense con fallback Piper — diseño

Fecha: 2026-09-13  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`) + `ServidorDePC/`  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida  
Supersede: en `2026-09-12-pc-server-stt-llm-design.md`, el “offload de TTS” pasa de fuera de alcance a este documento. STT/LLM no se reabren.

## Problema

La Pi sintetiza **toda** la voz con Piper `es_AR-daniela-high`. El acento es rioplatense, pero la prosodia sigue a máquina. Eso incluye respuestas del LLM, intents enlatados, rutinas y oraciones de cuento.

`ServidorDePC` ya hace STT GPU + LLM en la RTX 5080 (16 GB). El TTS sigue en la Raspberry. `cloud_mode` no sirve de molde: cambia a gTTS, exige internet y no carga Piper.

## Objetivo

1. Si hay LAN con el servidor Windows y Chatterbox está listo: la Pi **no sintetiza**. Manda el texto ya limpio y reproduce el WAV.
2. Si no hay PC, timeout, circuit TTS abierto o Chatterbox no listo: Piper Daniela local, igual que hoy.
3. Voz **femenina rioplatense** (identidad de Daniela), más humana. 100 % local: sin Edge, Azure ni Groq TTS.
4. Alcance de habla: charla LLM, intents, rutinas y **cuentos por oración**.
5. Keywords, tags, recorte a 25 palabras, ojos, GPIO y Android **siguen en la Pi**.

## Fuera de alcance (v1)

- WebSocket / streaming de PCM (el WAV cierra por oración).
- CosyVoice, XTTS, Kokoro, gTTS, Edge/Azure.
- LoRA `chatterbox-es-ar` (fase 2 si el clip de referencia no alcanza el acento).
- Mover a Windows el post-proceso de texto (`drop_prompt_leak`, tags, `_prepare_tts_text`).
- Descargar Piper de la Pi cuando la PC está sana.
- Cambiar `cloud_mode` / Groq.
- UI para elegir voz, velocidad o motor.
- Clonar la voz de Piper Daniela como referencia (el clon arrastra artefactos de Piper).

## Decisiones

- Motor: **Chatterbox Multilingual** (ResembleAI, MIT), `language_id=es`, `audio_prompt_path` = clip rioplatense.
- Transporte: **HTTP POST JSON → cuerpo WAV**. No base64. No WebSocket.
- La Pi es dueña del texto; Windows es un motor tonto texto→WAV.
- Circuit de TTS **independiente** del de STT/LLM.
- `/health` 200 sigue significando **STT+LLM calientes**. El JSON agrega `"tts": bool` sin bloquear chat si Chatterbox todavía carga.
- Watermark PerTh de Chatterbox: se deja. No se strippea.

## Arquitectura

```
texto listo en la Pi (LLM / intent / rutina / oración de cuento)
        │
        ├─ circuit TTS cerrado y POST /v1/audio/speech 200 → WAV → parlante
        └─ sin PC / timeout / 503 / WAV malo / circuit abierto → Piper local
```

Post-proceso **antes** del POST, siempre en la Pi:

`_parse_action_tags` → `_strip_tts_markup` → `_prepare_tts_text` → (cuentos: `split_into_sentences`)

`cloud_mode`: gTTS como hoy. No llama a Chatterbox.

Cuentos: misma tubería que Piper (oración N suena, N+1 se pide en paralelo). La síntesis N+1 es HTTP. Si N+1 falla, esa oración va a Piper; N no se corta; N+2 reintenta PC.

## Unidades

### `ServidorDePC/` (Windows)

| Archivo | Responsabilidad |
|---|---|
| `tts_engine.py` | Carga Chatterbox en CUDA. `ready`, `synthesize(text) -> bytes` (WAV PCM 16-bit mono, sample rate nativo ~24 kHz). Convierte el tensor float a WAV. |
| `voices/teo_es_ar.wav` | Clip de referencia **obligatorio** (~10 s, mujer, rioplatense, limpio, sin música). Si falta o no se lee, `ready=false`. No hay fallback a speaker genérico. |
| `voices/README.md` | Cómo grabar el clip (una frase hablada, silencio de bordes corto, 16–48 kHz). |
| `handlers.py` | `handle_health` suma `tts`. Nuevo `handle_speech`. |
| `server.py` | `POST /v1/audio/speech`. |
| `config.py` | Ruta del WAV, tope de caracteres, exaggeration/cfg_weight. |
| `requirements.txt` | `chatterbox-tts` (y deps CUDA que ya usa el server). |

Orden de `load()`: STT → LLM → TTS. Si CUDA OOM al cargar TTS: un reintento con bfloat16 y/o offload a CPU. Si igual falla: log, `tts.ready=false`, STT+LLM siguen.

Parámetros de generación fijos (sin UI): `exaggeration=0.5`, `cfg_weight=0.5` (defaults de Chatterbox). Tope de texto: **500 caracteres** (una oración de cuento entra; un PDF no).

El WAV de voz **no se commitea** (`voices/*.wav` en gitignore). Cada PC de Teo tiene su copia local. Sin ese archivo el health reporta `tts: false`.

### Cliente en la Pi

| Archivo | Responsabilidad |
|---|---|
| `pc_server_client.py` | `synthesize(text) -> bytes \| None`. Circuit TTS aparte (`fail_count_tts`, `open_until_tts`). `threading.Lock` en `_call`: `http.client` no es thread-safe y AudioWorker (STT/LLM) puede solaparse con SpeechWorker (TTS). El circuit STT/LLM **no** bloquea `synthesize`; el circuit TTS **no** bloquea `transcribe`/`complete`. |
| `workers.py` `SpeechWorker` | Recibe el **mismo** `PcServerClient` que `AudioWorker`. En `_speak_queued_text` / pipeline de oraciones: si no `cloud_mode` y `synthesize` devuelve WAV válido → `_play_wav_via_output_stream`. Si no → Piper (o SAPI/espeak si Piper no cargó). |
| `app.py` | Un `PcServerClient.from_env()` pasado a `SpeechWorker` y `AudioWorker` (EyeMode y UI tk). Si no hay client, SpeechWorker = solo Piper (tests actuales). |

Piper **sigue cargándose** al arrancar. El primer fallback no puede ser espeak.

Logs: `TTS_PC` / `TTS_PI` en `debug_logger`, análogo a `STT_PC` / `STT_PI`.

## Contratos HTTP

Auth: `Authorization: Bearer <PC_SERVER_TOKEN>`. Mismo token que STT/LLM.

### `GET /health`

200 `{"status":"ok","stt":true,"llm":true,"tts":<bool>}` solo si STT y LLM están calientes.  
503 si STT o LLM no están listos; el body igual incluye `"tts": ...`.  
401 sin token.  
El cliente actual no parsea `tts`. SpeechWorker se entera por el POST (200 vs 503).

### `POST /v1/audio/speech`

Body JSON:

```json
{ "input": "¡Hola! Qué lindo que estés acá.", "language": "es" }
```

| Código | Cuerpo | Cuándo |
|---|---|---|
| 200 | `audio/wav` (bytes, no JSON) | Síntesis OK |
| 400 | JSON `{"error":...}` | Falta `input`, vacío, o `len > 500` |
| 401 | JSON | Token |
| 503 | JSON | `tts.ready` es false |

El server no recorta a 25 palabras ni saca tags. Si la Pi manda markup, se lee.

## Timeouts y circuit TTS

| Fase | Timeout | Si falla |
|---|---|---|
| `POST /v1/audio/speech` | 10 s | Piper esa frase; cuenta fallo TTS |
| 503 | — | Piper; **no** cuenta fallo de infra |
| 401 | — | Abre circuit TTS (el de STT/LLM ya se abre en health/transcribe/chat con el mismo token) |
| Cuerpo vacío o sin header RIFF/`WAVE` | — | Piper esa frase; cuenta fallo TTS |

Circuit TTS: 2 fallos de infra seguidos → OPEN 30 s. Tras el cooldown, el siguiente `synthesize` vuelve a POST; si 200, cierra el circuit. No hay hilo probe. No reutiliza el timeout 120 s del LLM.

Silencio PCM válido (WAV de test todo cero) **no** es fallo: solo se rechaza cuerpo vacío o header inválido.

Frase por frase: un fallo no cancela el resto del cuento ni el turno.

## VRAM (RTX 5080 16 GB)

Residentes: Whisper large-v3 fp16 (~3–5 GB) + Gemma 12B Q5 (~8–9 GB) + Chatterbox (~4 GB). Cabe justo; puede no caber.

1. Cargar TTS al final. Si OOM: bfloat16 / offload, no matar STT/LLM.
2. Si sigue OOM: `tts=false`. La Pi usa Piper hasta que Teo baje `PC_LLM_N_GPU_LAYERS` y deje ~5 GB libres.
3. No se descarga el 12B ni Whisper de GPU en cada turno (el recargar sería peor que Piper).

## Failover

| TTS PC | Resultado |
|---|---|
| 200 WAV | Reproduce PC (`TTS_PC`) |
| 503 / no ready | Piper (`TTS_PI`), sin abrir circuit |
| timeout / 5xx / circuit abierto | Piper; circuit TTS según reglas de arriba |
| `cloud_mode` | gTTS; no hay POST speech |
| STT/LLM circuit abierto, TTS no | Igual se intenta Chatterbox (circuitos independientes) |

## Clip de referencia

Sin `ServidorDePC/voices/teo_es_ar.wav` el feature no se enciende. Teo lo copia a mano en la PC del servidor (no viaja a la Pi).

Criterio del clip: ~10 s, una sola locutora, castellano rioplatense, interior (no calle), sin música. No usar un WAV generado con Piper.

Fase 2 (no v1): LoRA `franclarke/chatterbox-es-ar` si el clone no convence al oído.

## Pruebas (TDD, sin GPU en CI)

WAV de test: silencio PCM 16-bit 24 kHz 200 ms con header RIFF válido (no Chatterbox real).

### Cliente (`test_pc_server_client.py`)

1. `synthesize` 200 → `bytes` que empiezan con `RIFF`.
2. Timeout / connection error → `None`, incrementa fallos TTS; STT `fail_count` intacto.
3. 503 → `None`, **no** abre circuit TTS.
4. 401 → circuit TTS open; no reintenta.
5. 2 timeouts TTS → OPEN 30 s; el tercer `synthesize` no socketea.
6. Circuit STT abierto no impide `synthesize`; circuit TTS abierto no impide `transcribe`.
7. Dos `_call` concurrentes no se pisan (lock).

### `SpeechWorker` (`test_tts_pc_route.py`)

8. Client 200 → se llama play con el PCM; Piper no sintetiza.
9. Client `None` → Piper (mock).
10. Circuit TTS abierto → cero HTTP; Piper.
11. `cloud_mode` → gTTS; cero POST speech.
12. Cuento 3 oraciones: la 2ª se pide mientras el play mock de la 1ª está “en curso”; si la 2ª falla, Piper en esa y la 3ª vuelve a `synthesize`.

### Server (`test_server.py`, engine fake)

13. Health 200 con `tts: false` si STT+LLM ready y TTS no.
14. Health 200 con `tts: true` si los tres ready.
15. POST `input` corto → 200 `audio/wav`.
16. `input` vacío o >500 → 400.
17. Sin token → 401.
18. TTS no ready → 503.

### Manual en hotspot

19. Frase corta: se oye Chatterbox, no Daniela.
20. Un cuento: oraciones seguidas, sin hueco largo al inicio de cada una.
21. Matar `ServidorDePC` a mitad: Piper esa frase; STT/LLM locales según el circuit que ya existe; al volver el server, Chatterbox de nuevo.
22. Quitar el WAV de referencia, reiniciar server: `tts: false`, peluche habla Piper, STT/LLM PC siguen.

## Criterio de hecho

- PC arriba + WAV de referencia presente: TEO habla Chatterbox rioplatense en charla, intents, rutinas y cuentos.
- Sin PC / sin WAV / OOM de TTS: misma voz Piper que hoy.
- Keywords no requieren Windows. Tags se ejecutan en la Pi aunque el audio venga de Chatterbox.
- Con hotspot caído no hay espera de 10 s en cada frase: circuit TTS OPEN tras 2 fallos, después Piper inmediato 30 s.

## Fase 2 (no implementar ahora)

- LoRA rioplatense si el clip no alcanza.
- Streaming WebSocket si se quiere primer audio <300 ms en frases largas.
- Ajustar exaggeration/cfg_weight con una escucha real (hoy quedan 0.5/0.5).
- Reservar VRAM del 12B de forma automática midiendo `nvidia-smi` al load.
