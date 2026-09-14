# PC Server TTS Chatterbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offload all spoken TTS to Chatterbox on `ServidorDePC` (WAV over HTTP); the Pi only plays, with Piper Daniela as fallback.

**Architecture:** Same `PcServerClient` as STT/LLM, with an independent TTS circuit and a `threading.Lock` around HTTP. `POST /v1/audio/speech` returns `audio/wav`. `SpeechWorker` tries PC then Piper. Stories keep sentence overlap; N+1 synth is HTTP.

**Tech Stack:** Python 3, stdlib `http.client` + `wave` on Pi, FastAPI + Chatterbox Multilingual on Windows, unittest (no GPU in CI).

**Spec:** `docs/superpowers/specs/2026-09-13-pc-server-tts-chatterbox-design.md`

## Global Constraints

- No WebSocket, CosyVoice, XTTS, Kokoro, gTTS-via-PC, Edge/Azure, or LoRA `chatterbox-es-ar` (fase 2).
- Pi owns tags, `_prepare_tts_text`, 25-word cut, keywords. Server is texto→WAV.
- `POST /v1/audio/speech` JSON `{"input": str, "language": "es"}`; 200 body is WAV bytes (`RIFF`/`WAVE`), not JSON.
- TTS timeout **10 s**. Circuit TTS: 2 infra fails → OPEN **30 s**. 503 does **not** open circuit.
- `/health` 200 still means STT+LLM ready; JSON adds `"tts": bool`.
- Circuits independent: STT open must not block `synthesize`; TTS open must not block `transcribe`.
- `cloud_mode` stays gTTS; zero POST speech.
- Piper still loads on the Pi. No generic Spanish speaker if the reference WAV is missing (`tts.ready=false`).
- Tests must not load Chatterbox or CUDA.
- `chatterbox-tts` goes in `ServidorDePC/requirements-tts.txt` (not core `requirements.txt`) so pip does not replace CUDA torch — same split as llama-cpp.
- Do **not** git commit unless Teo explicitly asks.

## File structure

| File | Role |
|---|---|
| `ProyectoParaRasperrypiV5/pc_server_client.py` | `synthesize`, TTS circuit, HTTP lock |
| `ProyectoParaRasperrypiV5/workers.py` | SpeechWorker PC WAV → play, else Piper; story overlap via HTTP |
| `ProyectoParaRasperrypiV5/app.py` | One `PcServerClient.from_env()` passed to SpeechWorker and AudioWorker |
| `ServidorDePC/tts_engine.py` | Chatterbox load/synthesize |
| `ServidorDePC/handlers.py` | `handle_speech`; health includes tts |
| `ServidorDePC/server.py` | Route + load TTS last |
| `ServidorDePC/config.py` | Voice path, max chars, exaggeration |
| `ServidorDePC/voices/README.md` | How to record `teo_es_ar.wav` |
| `ServidorDePC/requirements-tts.txt` | chatterbox-tts |
| `ServidorDePC/run.ps1` | pip install requirements-tts after core |

---

### Task 1: Cliente `synthesize` + circuit TTS + lock

**Files:**
- Modify: `ProyectoParaRasperrypiV5/pc_server_client.py`
- Test: `ProyectoParaRasperrypiV5/test_pc_server_client.py`

**Interfaces:**
- Produces: `TTS_TIMEOUT_S = 10.0`
- Produces: `PcServerClient.synthesize(text: str) -> bytes | None`
- Produces: `can_attempt_tts() -> bool`, `circuit_tts_open: bool`, `fail_count_tts: int`, `open_until_tts: float`
- Produces: `_call(..., circuit: str = "main")` — `"tts"` uses TTS circuit only
- Produces: `threading.Lock` around the actual HTTP/`request_fn` so concurrent `_call` cannot interleave

- [ ] **Step 1: Write failing tests** (append to `test_pc_server_client.py`)

```python
def _tiny_wav_bytes(sr: int = 24000, n: int = 240) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class TestSynthesizeTts(unittest.TestCase):
    def test_synthesize_200_devuelve_wav(self) -> None:
        wav = _tiny_wav_bytes()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/v1/audio/speech")
            payload = json.loads(kwargs["body"])
            self.assertEqual(payload["input"], "¡Hola!")
            self.assertEqual(payload["language"], "es")
            self.assertGreaterEqual(kwargs["timeout_s"], 10.0)
            return 200, wav

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        out = client.synthesize("¡Hola!")
        self.assertEqual(out, wav)
        self.assertEqual(client.fail_count_tts, 0)
        self.assertEqual(client.fail_count, 0)

    def test_synthesize_timeout_no_toca_circuit_stt(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 1)
        self.assertEqual(client.fail_count, 0)
        self.assertFalse(client.circuit_open)
        self.assertFalse(client.circuit_tts_open)

    def test_synthesize_503_no_abre_circuit(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 503, b'{"error":"tts not ready"}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 0)
        self.assertFalse(client.circuit_tts_open)

    def test_synthesize_401_abre_solo_tts(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            return 401, b"no"

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertTrue(client.circuit_tts_open)
        self.assertFalse(client.circuit_open)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(n["n"], 1)

    def test_dos_timeouts_tts_el_tercero_no_socketea(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("a"))
        self.assertIsNone(client.synthesize("b"))
        self.assertTrue(client.circuit_tts_open)
        self.assertEqual(n["n"], 2)
        self.assertIsNone(client.synthesize("c"))
        self.assertEqual(n["n"], 2)

    def test_circuit_stt_abierto_no_bloquea_synthesize(self) -> None:
        wav = _tiny_wav_bytes()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(path, "/v1/audio/speech")
            return 200, wav

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        client.fail_count = 2
        client.open_until = time.monotonic() + 30.0
        self.assertTrue(client.circuit_open)
        self.assertEqual(client.synthesize("hola"), wav)

    def test_circuit_tts_abierto_no_bloquea_transcribe(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(path, "/v1/audio/transcriptions")
            return 200, json.dumps({"text": "ok"}).encode()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        client.fail_count_tts = 2
        client.open_until_tts = time.monotonic() + 30.0
        self.assertTrue(client.circuit_tts_open)
        self.assertEqual(client.transcribe(b"RIFF"), "ok")

    def test_synthesize_sin_riff_cuenta_fallo_tts(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 200, b"not-a-wav"

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 1)

    def test_call_concurrent_serializa(self) -> None:
        import threading

        active = {"n": 0, "max": 0}
        lock = threading.Lock()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            with lock:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
            time.sleep(0.05)
            with lock:
                active["n"] -= 1
            return 200, _tiny_wav_bytes()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        threads = [
            threading.Thread(target=lambda: client.synthesize("a")),
            threading.Thread(target=lambda: client.transcribe(b"x")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(active["max"], 1)
```

- [ ] **Step 2: Run tests — expect FAIL** (`synthesize` missing)

```
python -m unittest test_pc_server_client.TestSynthesizeTts -v
```

Working directory: `ProyectoParaRasperrypiV5`

- [ ] **Step 3: Implement** in `pc_server_client.py`:
  - `import threading`
  - `TTS_TIMEOUT_S = 10.0`
  - `__init__`: `fail_count_tts = 0`, `open_until_tts = 0.0`, `self._http_lock = threading.Lock()`
  - `circuit_tts_open`, `can_attempt_tts()`
  - `_open_circuit_tts`, `_infra_fail_tts`, `_on_success_tts` (reset only TTS counters; still cache URL)
  - `_is_wav_body(raw: bytes) -> bool`: `len>=12 and raw[:4]==b"RIFF" and raw[8:12]==b"WAVE"`
  - `synthesize`: POST JSON, timeout 10s, circuit `"tts"`; 401 opens TTS only; 503 → None no fail; 200 invalid WAV → None + TTS fail; 200 valid → bytes
  - `_call(..., circuit: str = "main")`: if `circuit=="tts"` gate on `circuit_tts_open`, else `circuit_open`. Wrap `request_fn` / `_http_request` in `self._http_lock`. Infra fail / success dispatch to the matching circuit. 401 handling stays in `synthesize`/`transcribe` (not inside `_call`).

- [ ] **Step 4: Run tests — expect PASS** including the whole `test_pc_server_client.py` file.

---

### Task 2: ServidorDePC `tts_engine` + `handle_speech` + health `tts`

**Files:**
- Create: `ServidorDePC/tts_engine.py`
- Create: `ServidorDePC/voices/.gitkeep`, `ServidorDePC/voices/README.md`
- Create: `ServidorDePC/requirements-tts.txt`
- Modify: `ServidorDePC/handlers.py`, `server.py`, `config.py`, `test_server.py`, `.gitignore`, `run.ps1`

**Interfaces:**
- Consumes: existing `handle_health`/`handle_transcribe`/`handle_chat` auth helper
- Produces: `TtsEngine.ready: bool`, `load() -> None`, `synthesize(text: str) -> bytes`
- Produces: `handle_health(stt, llm, token, auth, tts=None) -> (int, dict)` with `"tts": bool`
- Produces: `handle_speech(tts, token, auth, raw_body, log_fn=None, peer=None) -> (int, bytes|dict, str)` media type `audio/wav` or `application/json`
- Produces: `TTS_VOICE_PATH`, `TTS_MAX_CHARS=500`, `TTS_EXAGGERATION=0.5`, `TTS_CFG_WEIGHT=0.5`

- [ ] **Step 1: Write failing tests** in `ServidorDePC/test_server.py`

Add `FakeTts` with `ready` and `synthesize(text)->bytes`. Change `handle_health` calls to pass tts when asserting `tts` key.

```python
class FakeTts:
    def __init__(self, ready: bool = True, wav: bytes | None = None) -> None:
        self.ready = ready
        self.wav = wav if wav is not None else _tiny_wav()
        self.last_text: str | None = None

    def synthesize(self, text: str) -> bytes:
        self.last_text = text
        return self.wav
```

Tests (names from spec 13–18):
- `test_200_stt_llm_listos_tts_false` → 200, `tts` is False
- `test_200_tres_listos_tts_true` → 200, `tts` is True
- `test_speech_input_devuelve_wav` → 200, payload starts with `RIFF`, `last_text` equals input
- `test_speech_vacio_400`
- `test_speech_mas_de_500_400` (501 chars)
- `test_speech_sin_token_401`
- `test_speech_no_ready_503`
- Existing health tests still pass with optional `tts=None` (`tts` key False)

Also: `test_gitignore_voices_wav`, `test_requirements_tts_not_in_core`.

- [ ] **Step 2: Run — expect FAIL** (`handle_speech` missing)

```
python -m unittest test_server.py -v
```

Working directory: `ServidorDePC`

- [ ] **Step 3: Implement**

`config.py` add:

```python
TTS_VOICE_PATH = Path(os.environ.get("PC_TTS_VOICE") or (ROOT / "voices" / "teo_es_ar.wav"))
TTS_MAX_CHARS = int(os.environ.get("PC_TTS_MAX_CHARS") or "500")
TTS_EXAGGERATION = float(os.environ.get("PC_TTS_EXAGGERATION") or "0.5")
TTS_CFG_WEIGHT = float(os.environ.get("PC_TTS_CFG_WEIGHT") or "0.5")
TTS_LANGUAGE = os.environ.get("PC_TTS_LANGUAGE") or "es"
```

`tts_engine.py`: `load()` if voice file missing → log, `ready=False`. Else import Chatterbox multilingual, `from_pretrained(device="cuda")` (pass `t3_model="v3"` if the installed API accepts it). On CUDA OOM/Exception, one retry `device="cpu"`. `synthesize(text)` calls `generate(..., language_id="es", audio_prompt_path=str(path), exaggeration=..., cfg_weight=...)`, converts float PCM to 16-bit WAV at `model.sr`. Never import Chatterbox at module import (tests).

`handle_health`: add `tts=None`; `"tts": bool(getattr(tts, "ready", False))`. 200 still only if stt and llm.

`handle_speech`: auth; if not tts.ready → 503 JSON; parse JSON `input`; strip; empty or `len>TTS_MAX_CHARS` → 400; call `tts.synthesize`; return `(200, wav, "audio/wav")`.

`server.py`: `tts_engine = TtsEngine()`; pass into health; new POST `/v1/audio/speech` returning `Response(wav, media_type="audio/wav")` or JSONResponse. `main()`: `stt.load(); llm.load(); tts.load()`.

`.gitignore`: `voices/*.wav`

`voices/README.md`: 10 s, one female rioplatense speaker, no music, not Piper-generated; copy to `teo_es_ar.wav`.

`requirements-tts.txt`: `chatterbox-tts` (no torch pin).

`run.ps1`: after core pip, `pip install -r requirements-tts.txt --no-cache-dir` (do not fail the whole script if TTS pip fails; print warning).

- [ ] **Step 4: Run `test_server.py` — expect PASS**

---

### Task 3: SpeechWorker + app wiring

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`SpeechWorker.__init__`, `_speak_queued_text`, `_speak_sentence_pipeline`)
- Modify: `ProyectoParaRasperrypiV5/app.py` (both SpeechWorker construction sites)
- Test: `ProyectoParaRasperrypiV5/test_tts_pc_route.py`

**Interfaces:**
- Consumes: `PcServerClient.synthesize`, `can_attempt_tts`
- Produces: `SpeechWorker(pc_client=None)`
- Produces: `_wav_bytes_to_pcm(wav: bytes) -> tuple[np.ndarray, int] | None`
- Produces: `_synthesize_pc_pcm(text: str) -> tuple[np.ndarray, int] | None` (None if cloud_mode, no client, synthesize None, or bad wav)
- Story pipeline: synth helper tries PC then Piper; play N on a thread while synth N+1

- [ ] **Step 1: Write failing tests** in `test_tts_pc_route.py`

```python
# FakeClient with synthesize returning WAV or None; can_attempt_tts; call_count
# SpeechWorker(pc_client=fake), _piper_voice=object(), patch _play_wav_via_output_stream and _synthesize_piper_pcm

# test_pc_200_reproduce_sin_piper
# test_pc_none_usa_piper
# test_circuit_tts_cerrado_cero_http  -> can_attempt_tts False, synthesize never called, piper used
# test_cloud_mode_cero_synthesize
# test_cuento_segunda_se_pide_durante_play: FakeClient.synthesize records times; play mock sleeps 0.05s;
#   pipeline ["Uno.","Dos.","Tres."]; assert len(texts)==3; if second synthesize raises/returns None once,
#   piper called for that sentence and third still hits synthesize
```

Use `_tiny_wav` 24 kHz. `_wav_bytes_to_pcm` must return float32 PCM and 24000.

- [ ] **Step 2: Run — expect FAIL**

```
python -m unittest test_tts_pc_route.py -v
```

- [ ] **Step 3: Implement**
  - `SpeechWorker.__init__(..., pc_client=None)` store `self.pc_client`
  - `_wav_bytes_to_pcm`: `wave` + numpy int16→float32; invalid → None; header-only empty frames → None
  - `_synthesize_pc_pcm`: skip if `_cloud_mode`; if client is None or not `can_attempt_tts()` return None; `synthesize`; decode
  - `_speak_queued_text`: after cloud check, if `_synthesize_pc_pcm` ok → play + log `TTS_PC`; else existing piper/sapi/espeak + log `TTS_PI` when falling back from a present client
  - `_speak_sentence_pipeline`: if cloud, keep sequential `_speak_queued_text`. Else `synth(text)` = `_synthesize_pc_pcm` or piper with `PIPER_STORY_LENGTH_SCALE`. Same play-thread overlap as today.
  - `app.py` both sites: `pc_client = PcServerClient.from_env()` (try/except None); pass into SpeechWorker and AudioWorker (`pc_client=pc_client`). Do not let AudioWorker create a second client when one was passed.

- [ ] **Step 4: Run `test_tts_pc_route.py` and `test_tts_voice.py` — expect PASS**

---

### Task 4: Verify + upload Pi files

- [ ] **Step 1:**

```
python -m unittest test_pc_server_client.py test_tts_pc_route.py test_tts_voice.py
```

in `ProyectoParaRasperrypiV5`

```
python -m unittest test_server.py
```

in `ServidorDePC`

- [ ] **Step 2:** Upload Pi runtime files with `uploading-to-raspberry-pi` skill: `pc_server_client.py`, `workers.py`, `app.py`, `test_pc_server_client.py`, `test_tts_pc_route.py`. Do not upload secrets. Do not start `app.py`.

- [ ] **Step 3:** Tell Teo: copy `teo_es_ar.wav` into `ServidorDePC/voices/`, reinstall `requirements-tts.txt` on the PC, restart `run.ps1`, then restart the Pi app.

## Spec coverage

| Spec item | Task |
|---|---|
| synthesize WAV / independent circuit / 503 / 401 / lock | 1 |
| health tts / POST speech / 400/401/503 / engine / missing WAV | 2 |
| SpeechWorker play / Piper fallback / cloud_mode / story overlap / shared client | 3 |
| unittest + upload | 4 |
| LoRA / WebSocket / auto VRAM nvidia-smi | out of scope |
