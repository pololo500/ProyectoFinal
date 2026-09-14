# Servidor PC: TTS Piper + Elena — diseño

Fecha: 2026-09-13  
Producto: peluche TEO + `ServidorDePC/`  
Estado: aprobado en conversación (arquitectura, componentes, flujo, tests)  
Supersede: `2026-09-13-pc-server-tts-chatterbox-design.md` y `2026-09-13-pc-server-tts-cosyvoice2-design.md`. Esos motores quedan fuera.

## Problema

Chatterbox y CosyVoice 2 no sirven para Teo (latencia y audio incoherente). La Pi ya habla con Piper `es_AR-daniela-high` y, con internet, existe Elena Neural en `ProyectoTtsMp3`. El TTS de calidad tiene que correr en Windows; la Pi solo reproduce.

## Objetivo

1. Quitar del servidor Chatterbox y CosyVoice (código, deps, probes, clone, config de clips/pesos).
2. Windows sintetiza con **Piper** (mismo modelo y mismos parámetros de diálogo que la Pi).
3. Switch explícito `prefer_elena`: con `true` y Microsoft alcanzable → Elena Neural; si no → Piper en esa misma request.
4. Contrato HTTP intacto. La Pi no se modifica.

## Contrato (no se reabre)

- `POST /v1/audio/speech` JSON `{"input": "..."}` (opcional `language`) → WAV 16-bit PCM.
- Auth Bearer igual que hoy. `input` vacío o > `TTS_MAX_CHARS` (500) → 400.
- `/health` campo `tts`: `true` si Piper cargó. Elena no forma parte de `ready`.
- Timeout de la Pi sigue en 10 s. No se cambia `pc_server_client.py`.
- Circuit TTS de la Pi: si la PC devuelve vacío/timeout, la Pi usa su Piper local. Eso ya existe.

El JSON no trae flag de cuento. Piper en la PC usa siempre escalas de **diálogo** (`length_scale=1.20`). `PIPER_STORY_LENGTH_SCALE=1.35` queda solo en la Pi para el fallback local de cuentos.

## Switch `prefer_elena`

Prioridad:

1. Env `PC_TTS_PREFER_ELENA` si está definida (no vacía).
2. Si no, primer línea no vacía de `ServidorDePC/tts_prefer_elena.txt`.
3. Si no hay ni env ni archivo: **`true`**.

Valores true: `1`, `true`, `yes`, `on` (case-insensitive).  
Valores false: `0`, `false`, `no`, `off`.  
Cualquier otro → default `true`.

Comportamiento:

| `prefer_elena` | Red / Elena | Motor |
|---|---|---|
| `false` | irrelevante | Piper. No se llama a edge-tts. |
| `true` | Elena OK | Elena Neural. |
| `true` | sin red, timeout, error, MP3 vacío | Piper en la misma request. |

Internet = Elena pudo completar contra Microsoft. No hay ping a Google ni probe aparte.

Timeout de Elena: **6 s**. Si se pasa, Piper. Tiene que entrar en los 10 s de la Pi.

## Motores

### Piper (offline, obligatorio para `ready`)

- Paquete `piper-tts`.
- Modelo `es_AR-daniela-high` (`es/es_AR/daniela/high` en Hugging Face `rhasspy/piper-voices`).
- Cache: `%USERPROFILE%\.edge_ai_models\piper` (`es_AR-daniela-high.onnx` + `.onnx.json`). Misma ruta que la Pi.
- Parámetros: `length_scale=1.20`, `noise_scale=0.667`, `noise_w_scale=0.98`.
- Si el ONNX no está, se descarga al `load()` (hace falta red esa vez). Si la descarga o `PiperVoice.load` falla → `ready=false`, `/health` `tts: false`.
- Salida: float32 → WAV 16-bit mono, sample rate del modelo (típicamente 22050).

### Elena (online, opcional)

- Misma voz que `ProyectoTtsMp3`: `es-AR-ElenaNeural`, `rate="-8%"`.
- Mismo `prepare_tts_text`: colapsar espacios; si el texto no termina en `.!?…` agregar `.`; vacío sigue vacío.
- `edge-tts` → MP3 → decode a float32 (soundfile; si falla, el mismo orden que `CloudTTS._decode_mp3` en la Pi: minimp3, pydub) → WAV 16-bit mono.
- Copiar la lógica a `ServidorDePC/tts_elena.py`. **No** importar `ProyectoTtsMp3` (esa app Tk se queda).
- Elena no se carga al arranque. Un fallo no pone `ready=false`.

## Archivos

Crear:

- `ServidorDePC/tts_piper.py`
- `ServidorDePC/tts_elena.py`

No versionar `tts_prefer_elena.txt`. Default en código = `true`. Teo puede crear el archivo local con `false` para forzar Piper, o usar `PC_TTS_PREFER_ELENA`.

Modificar:

- `ServidorDePC/tts_engine.py` — fachada Piper + Elena. Sin CosyVoice.
- `ServidorDePC/config.py` — `prefer_elena()`; quitar `TTS_VOICE_PATH`, `TTS_PROMPT_TEXT_PATH`, `TTS_MODEL_DIR`, `COSYVOICE_ROOT`.
- `ServidorDePC/requirements-tts.txt` — `piper-tts`, `edge-tts`. Sin CosyVoice/Chatterbox/wetext/lightning.
- `ServidorDePC/run.ps1` — no clonar CosyVoice; `pip install -r requirements-tts.txt` para Piper/Elena.
- `ServidorDePC/test_server.py` — tests de routing y health; sacar tests CosyVoice.
- `ServidorDePC/.gitignore` — mantener `third_party/CosyVoice/` y `pretrained_models/`; agregar `tts_prefer_elena.txt`.

Borrar del árbol de código:

- `ServidorDePC/probe_cosyvoice.py`

No borrar a la fuerza GBs en `third_party/CosyVoice` ni `pretrained_models` (gitignore). Dejan de usarse. No se vuelven a clonar.

No tocar:

- `ProyectoParaRasperrypiV5/` (Pi, Piper local, circuit, timeout).
- `ProyectoTtsMp3/` (generador MP3 de escritorio).

## `TtsEngine`

```python
class TtsEngine:
    def load(self) -> None: ...
    def synthesize(self, text: str) -> bytes: ...  # WAV o b""
    ready: bool  # True solo si Piper cargó
```

`synthesize`:

1. Texto vacío → `b""`.
2. Si `prefer_elena`: intentar Elena (6 s). WAV no vacío → devolver.
3. Piper. Si Piper no está o falla → `b""` → handler 500.

Log: `[TTS] Piper listo` al load; por request, motor usado (`elena` o `piper`) y ms.

## Fuera de alcance

- Cambiar la Pi, streaming, CosyVoice/Chatterbox, voces Windows SAPI en el servidor, gTTS, flag de cuento en el JSON, ping de internet aparte, borrar pesos CosyVoice del disco.

## Criterio de hecho

- `prefer_elena=false` nunca llama a Elena (test con fake).
- `prefer_elena=true` + Elena OK → WAV de Elena (fake communicate).
- `prefer_elena=true` + Elena error/timeout → Piper (fake).
- Piper ausente → `ready=false` → health `tts: false`.
- `prepare_tts_text` replica los casos de `ProyectoTtsMp3/test_synthesizer.py`.
- `requirements-tts.txt` no contiene `cosyvoice` ni `chatterbox`.
- `run.ps1` no clona FunAudioLLM/CosyVoice.
- `handlers.handle_speech` sigue devolviendo `audio/wav`.
- Tests de STT/LLM/health existentes siguen verdes.
