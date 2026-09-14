# Servidor PC: STT + LLM 8B con fallback en la Pi — diseño

Fecha: 2026-09-12  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`) + módulo nuevo `ServidorDePC/`  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

Hoy todo el inferencia corre en la Raspberry Pi 5 (8 GB): `faster-whisper` medium int8 (o Vosk si SIGBUS) y Llama 3.2 3B Q4_K_M en CPU (`n_gpu_layers=0`). La transcripción tarda ~5 s; el 3B genera a ~4–6 tok/s (`max_tokens=80` → decenas de segundos; timeout 120 s pensado para OpenMP colgado, no para un nene).

Hay una PC en la misma LAN (Core Ultra i9, RTX 5080 16 GB VRAM, 32 GB RAM) que puede servir un 8B en GPU en &lt;1–2 s y Whisper large en &lt;0,5 s. La LAN la arma el hotspot del celular; Teo ya comprobó que **Pi ↔ PC se pinguean**. Si no hay Wi‑Fi o el servidor no responde, el peluche tiene que seguir igual que hoy.

`cloud_mode` **no** es el molde: manda STT+LLM a Groq, cambia TTS a gTTS y **no carga** Whisper ni el 3B. El camino LAN es híbrido.

## Objetivo

1. Tras el VAD, intentar STT y (si aplica) LLM en `ServidorDePC` por HTTP.
2. Si el servidor no está, timeout o circuit open: mismo STT local + 3B + Piper que hoy.
3. Keywords, Piper `es_AR-daniela-high`, ojos, GPIO y app Android **no** dependen de la PC.
4. Subir el modelo de charla a Llama 3.1 8B Instruct Q4_K_M **solo en la PC**. En la Pi el fallback sigue siendo 3B. Nunca 8B en la Pi (~1,5 tok/s).

## Fuera de alcance (v1)

- WebSocket, streaming de audio, partials, barge-in.
- Offload de TTS, cámara, intents/keywords, GPIO.
- vLLM, Ollama como runtime principal, mDNS/Bonjour.
- Relé por la app Android (no hace falta: el ping Pi↔PC funciona).
- Descargar Whisper/3B de la Pi cuando la PC está sana (el primer fallback sería una eternidad).
- Cambiar `cloud_mode` / Groq.
- Descubrimiento UDP invertido (fase 2 si el DHCP molesta).

## Decisiones de transporte

El pipeline actual cierra el clip **después** del VAD (1,2 s de silencio o 8 s tope) y recién transcribe. El WAV 16 kHz mono 16-bit pesa ~32 KB/s (32–256 KB). En Wi‑Fi eso son décimas de segundo; el costo es el compute en la Pi.

**v1: HTTP POST del WAV cerrado + HTTP POST de chat.** No WebSocket. Un WebSocket solo ganaría si se stremea *durante* el habla; hoy no hay overlap, y en hotspot suma reconexiones.

## Arquitectura

La Pi sigue dueña del turno. `ServidorDePC` es un proceso Windows con Whisper GPU + 8B residentes. Tras el clip:

1. `GET /health` (≤300 ms). Si falla → path local completo.
2. `POST /v1/audio/transcriptions` (WAV). Si falla → STT local. Si el LLM de la PC sigue sano, **igual se usa el 8B**.
3. Sanitizar PII + keywords + motores (juego/cuento/yoga) **siempre en la Pi**.
4. Si `should_allow_llm` (unknown / reflexión de cuento, sin motor activo, etc.): `POST /v1/chat/completions` con system + historial + user. Si falla → 3B local.
5. Post-proceso en la Pi: `drop_unsolicited_story_offer`, `drop_prompt_leak`, recorte 25 palabras, `_parse_action_tags`, Piper.

```
mic/VAD (Pi) → [health PC]
                 ├─ OK → STT GPU → keywords Pi → [LLM 8B si unknown] → tags/Piper
                 └─ fail → STT Pi → keywords Pi → [LLM 3B si unknown] → tags/Piper
```

## Unidades

### `ServidorDePC/` (nuevo, Windows)

Proceso único FastAPI en `0.0.0.0:8090` (8080 es la API parental de la Pi).

| Archivo | Responsabilidad |
|---|---|
| `server.py` | HTTP, auth Bearer, `/health`, `/v1/audio/transcriptions`, `/v1/chat/completions` |
| `stt_engine.py` | Carga y transcribe `faster-whisper` `large-v3`, `device=cuda`, `compute_type=float16` (INT8 en Blackwell/50-series suele fallar con cuBLAS) |
| `llm_engine.py` | Carga GGUF Llama 3.1 8B Instruct Q4_K_M (`bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` / `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`), `n_gpu_layers=-1`, `n_ctx=2048`, warmup al arrancar |
| `config.py` | Puerto, token, rutas, sampling |
| `requirements.txt` | fastapi, uvicorn, faster-whisper (CUDA), llama-cpp-python (CUDA) |
| `run.ps1` | Driver/CUDA, regla firewall inbound TCP 8090, evitar suspensión |

El server **no** parsea tags ni keywords. Es un motor. La Pi manda el `system` prompt (`fallback_llm._SYSTEM_PROMPT` + hint de emoción).

Plan B si el wheel CUDA de `llama-cpp-python` no offloadea en la 5080: `llama-server` hijo (binario CUDA 12.8+, `-ngl 99`, `--api-key`) y FastAPI solo hace Whisper + proxy de chat. Blackwell necesita driver R570+ / CUDA 12.8+ (`sm_120`). Verificar con log que las capas están en GPU; si el 8B queda en CPU puede ser *peor* que el 3B de la Pi.

VRAM: 8B Q4 ~5–6 GB + large-v3 fp16 ~4–5 GB cabe en 16 GB. STT y LLM son **secuenciales** (igual que en la Pi); ambos quedan residentes.

### Cliente en la Pi

| Archivo | Responsabilidad |
|---|---|
| `pc_server_client.py` (nuevo) | `health()`, `transcribe(audio) → str`, `complete(messages) → str`, circuit breaker, timeouts |
| `workers.py` | En `_handle_segment`: STT PC→local; LLM PC→`fallback_llm`; **no** usar `cloud_mode` |
| Env | `PC_SERVER_URL` (ej. `http://192.168.43.10:8090`), `PC_SERVER_TOKEN` |

Caché de la última URL que respondió `/health` 200 (archivo chico). El DHCP del hotspot cambia al recrear la red; v1 no hace mDNS. IPv4 forzado.

### Lo que no se toca

`alsa_capture.py`, Piper, `session_policy` keywords, `api_server.py` (Android), `pairing.py` (token parental distinto del token PC), `cloud_services.py`.

El 3B sigue `load()` + `warmup()` **antes** del mic, igual que hoy.

## Contratos HTTP

Auth: `Authorization: Bearer <PC_SERVER_TOKEN>`. 401 → log, circuit open, no martillar.

### `GET /health`

200 `{"status":"ok","stt":true,"llm":true}` solo si ambos modelos están calientes.  
503 mientras cargan. El cliente **no** cuenta 503 de carga como fallo de infra del circuit.

### `POST /v1/audio/transcriptions`

La Pi manda el **mismo audio ya preprocesado** que Whisper local (`_preprocess_audio`: DC, normalizar, pad si &lt;1,2 s), empaquetado en WAV 16 kHz mono 16-bit. Query/form: `language=es`. El server aplica el `initial_prompt` rioplatense (copia de `AudioWorker._WHISPER_INITIAL_PROMPT`), `vad_filter=False`, `beam_size` igual que `whisper_beam_size()`. Respuesta OpenAI-like: `{"text":"..."}`.

### `POST /v1/chat/completions`

Body compatible OpenAI: `messages`, `max_tokens=80`, `temperature=0.70`, `top_p=0.9`. El server traduce a llama.cpp: `top_k=40`, `repeat_penalty=1.15`, mismos `stop` que `fallback_llm.complete_sync`. Respuesta: `choices[0].message.content`. La Pi no asume que el server recortó a 25 palabras ni que sacó ofertas de cuento.

## Timeouts y circuit breaker

| Fase | Timeout | Si falla |
|---|---|---|
| TCP + `GET /health` | 300 ms | Path local este turno |
| STT remoto | 3 s | STT local; LLM PC si health LLM ok |
| LLM remoto | 5 s | 3B local (texto ya transcrito) |

Circuit: 2 fallos seguidos de **infra** (connect, timeout, 5xx de transcribe/chat). **No** cuenta 401 (config) ni 503 de carga. OPEN 30 s → un probe `/health` → si 200, cierra. El timeout 120 s de `llm_generate_timeout_s()` **no** se reutiliza para HTTP: deja el mic muteado y la cara “pensando”.

Wi‑Fi down (sin gateway): ni siquiera health; local ya.

PC dormido: todos los turnos a la Pi. `run.ps1` documenta desactivar suspensión.

## Failover por turno (matriz)

| STT PC | LLM PC | Resultado |
|---|---|---|
| OK | no se llama (keyword) | Texto PC + intent enlatado |
| OK | OK | Texto PC + 8B |
| OK | fail | Texto PC + 3B |
| fail | OK | Texto Pi + 8B |
| fail | fail / circuit | Path actual |

Frase `unknown_fallback` enlatada: solo si tampoco contestó el 3B (igual que hoy).

Logs: `STT_PC` / `STT_PI` / `LLM_PC` / `LLM_PI` en `debug_logger`.

## Sampling y prompt

Reusar `_SYSTEM_PROMPT` y `_build_messages` de `fallback_llm.py`. `n_ctx` en PC **2048** (el default 1024 de la Pi es deuda; Agents.md ya pide 2048). Historial: `ConversationMemory` (default 2 turnos). Emoción: el hint se arma en la Pi y viaja en `messages`.

## Red / hotspot

- Confirmado: unicast Pi↔PC funciona en el teléfono de Teo.
- Broadcast/mDNS pueden seguir rotos; v1 no los usa.
- Firewall Windows: inbound TCP 8090 en redes privadas.
- No exponer el puerto a Internet. El hotspot no es red de confianza: el token no es opcional.
- CGNAT del celular no aplica al tráfico LAN.

## Pruebas (TDD, sin GPU en CI)

### Cliente (`test_pc_server_client.py`)

1. health 200 → `available`.
2. health timeout / refused → `unavailable`, cuenta fallo.
3. health 503 → `unavailable` este turno, **no** abre circuit.
4. 401 → no reintenta, circuit open.
5. 2 timeouts STT/LLM → circuit OPEN 30 s; el tercer intento ni socketea.
6. Tras cooldown, un health 200 cierra el circuit.

### `AudioWorker` (HTTP mock, sin GGUF)

7. PC STT OK + `"juguemos veo veo"` → no llama chat completions.
8. PC STT OK + unknown → llama chat; la respuesta 8B llega a Piper (mock).
9. STT PC timeout → transcribe local; unknown igual llama 8B.
10. LLM PC timeout → 3B local.
11. Circuit open → no hay HTTP; path actual.
12. No entra a `cloud_mode` (Piper sigue, 3B sigue cargado).

### Server (engines fake)

13. `/health` 503 hasta que ambos `ready`, después 200.
14. Transcribe WAV chico → `{"text":...}`.
15. Chat con messages → content string; sin token → 401.

### Manual en hotspot

16. Desde la Pi: `curl -4 http://IP:8090/health`.
17. POST de un WAV de `tests/audio_frases/`.
18. Un chat de 80 tokens; nvidia-smi / log de capas GPU.
19. Matar el server a mitad de sesión y oír fallback local.

## Criterio de hecho

- Unknown con PC arriba: STT GPU + 8B; latencia de LLM percibida &lt; ~2 s (más STT GPU, no 5 s de Whisper Pi).
- Sin PC / hotspot caído: mismo comportamiento que hoy (Vosk/Whisper Pi + 3B + Piper).
- Keywords (abrazo, veo veo, piedra, llama a mamá, cuento, música) **no** requieren la PC. Charla tipo «hola» sigue yendo al LLM (8B o 3B).
- Tags `[NOTIFY_PARENT]`, `[INTENTS_OFF]`, `[PLAY_MUSIC]`, `[EXPRESSION:…]` siguen parseándose en la Pi.
- TTS sigue siendo Daniela Piper, no gTTS.

## Fase 2 (no implementar ahora)

- Beacon UDP / última IP automática si cargar `PC_SERVER_URL` a mano cansa.
- Relé Android solo si un teléfono distinto aísla clientes.
- WebSocket si se cambia el producto a transcribir *durante* el habla.
- Q5/Q8 o Gemma/Qwen si el 8B Llama no convence en español infantil (medir, no adivinar).
