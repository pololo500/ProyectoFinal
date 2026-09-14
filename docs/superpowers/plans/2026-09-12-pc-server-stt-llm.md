# PC Server STT + LLM 8B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offload STT and LLM to `ServidorDePC` on the Windows GPU box, with the Pi keeping VAD/keywords/Piper and falling back to local Whisper/Vosk + 3B.

**Architecture:** Pi `PcServerClient` (stdlib HTTP, IPv4, circuit breaker) talks to FastAPI `:8090`. Health → POST WAV → keywords on Pi → POST chat if unknown. Timeouts 300ms / 3s / 5s. Never reuse the 120s llama-cpp timeout. Do not use `cloud_mode`.

**Tech Stack:** Python 3, stdlib `http.client` on Pi, FastAPI/uvicorn + faster-whisper CUDA + llama-cpp-python CUDA on Windows, unittest.

**Spec:** `docs/superpowers/specs/2026-09-12-pc-server-stt-llm-design.md`

## Global Constraints

- No WebSocket, mDNS, vLLM, Ollama-as-primary, TTS offload, or 8B on the Pi.
- Tags parsed only on the Pi. Server is a dumb engine.
- Blackwell Whisper: `float16`, not INT8.
- `n_ctx=2048` on PC. Token via `PC_SERVER_TOKEN` / file. Port 8090.
- Tests must not load GGUF or real Whisper.

---

### Task 1: Pi HTTP client + circuit breaker

**Files:**
- Create: `ProyectoParaRasperrypiV5/pc_server_client.py`
- Test: `ProyectoParaRasperrypiV5/test_pc_server_client.py`

**Interfaces:**
- Produces: `PcServerClient.from_env()`, `health() -> bool`, `transcribe(wav: bytes) -> str | None`, `complete(messages: list[dict]) -> str | None`, `can_attempt() -> bool`, `pcm_float32_to_wav_bytes()`

- [ ] TDD client (inject `request_fn`). Spec tests 1–6.
- [ ] Implement stdlib HTTP, 401 opens circuit, 503 health does not count, cache last URL.

### Task 2: ServidorDePC handlers

**Files:**
- Create: `ServidorDePC/config.py`, `stt_engine.py`, `llm_engine.py`, `handlers.py`, `server.py`, `requirements.txt`, `run.ps1`
- Test: `ServidorDePC/test_server.py`

- [ ] TDD handlers with fake engines (health 503/200, transcribe WAV, chat, 401).
- [ ] FastAPI wraps handlers. Engines load CUDA models; skip load in tests.

### Task 3: AudioWorker integration

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`AudioWorker.__init__`, `_handle_segment`, `_story_reflection_question`)
- Modify: `ProyectoParaRasperrypiV5/app.py` (optional; client from env inside AudioWorker)
- Test: `ProyectoParaRasperrypiV5/test_pc_stt_llm_route.py`

- [ ] TDD routing helpers (keyword skips chat, unknown uses PC, STT fail still 8B, LLM fail uses 3B, circuit skips HTTP).
- [ ] Wire `_handle_segment` without touching `cloud_mode`.

### Task 4: Verify

- [ ] `python -m unittest test_pc_server_client.py test_pc_stt_llm_route.py` in Pi folder
- [ ] `python -m unittest test_server.py` in ServidorDePC
- [ ] Upload Pi `.py` via uploading-to-raspberry-pi skill
