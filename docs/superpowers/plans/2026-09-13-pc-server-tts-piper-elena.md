# Piper + Elena TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quitar CosyVoice/Chatterbox del servidor Windows y sintetizar con Piper `es_AR-daniela-high`; si `prefer_elena` y Microsoft responde, usar Elena Neural.

**Architecture:** `TtsEngine` fachada. `load()` solo Piper (`ready`). `synthesize()`: si `prefer_elena()` intenta Elena (6 s) y si falla usa Piper. HTTP `/v1/audio/speech` no cambia. La Pi no se toca.

**Tech Stack:** Python 3.12, `piper-tts`, `edge-tts`, `soundfile`, unittest.

## Global Constraints

- No tocar `ProyectoParaRasperrypiV5/` ni `ProyectoTtsMp3/`.
- No commit a menos que Teo lo pida.
- `ready` = Piper cargó. Elena no bloquea arranque.
- Timeout Elena 6 s. Piper diálogo: length_scale=1.20, noise_scale=0.667, noise_w_scale=0.98.
- Default `prefer_elena=true`. Env `PC_TTS_PREFER_ELENA` gana sobre `tts_prefer_elena.txt`.
- WAV 16-bit PCM mono.

---

### Task 1: Config `prefer_elena` + `prepare_tts_text`

**Files:**
- Modify: `ServidorDePC/config.py`
- Create: `ServidorDePC/tts_elena.py` (solo texto + constantes en este task; synthesize después)
- Modify: `ServidorDePC/test_server.py`

**Interfaces:**
- Produces: `config.prefer_elena(env=None, path=None) -> bool`; `tts_elena.prepare_tts_text(text: str) -> str`; `VOICE_NAME`, `VOICE_RATE`, `ELENA_TIMEOUT_S = 6.0`

- [ ] **Step 1: Tests RED** `TestPreferElena` + `TestPrepareTtsText` en `test_server.py` (casos iguales a `ProyectoTtsMp3/test_synthesizer.py`).
- [ ] **Step 2: Correr tests, confirmar FAIL por import.**
- [ ] **Step 3: Implementar `prefer_elena` y `prepare_tts_text`.**
- [ ] **Step 4: Tests PASS.**

### Task 2: WAV helper + Elena MP3→WAV (inyectable) + Piper engine

**Files:**
- Create: `ServidorDePC/tts_wav.py`
- Modify: `ServidorDePC/tts_elena.py`
- Create: `ServidorDePC/tts_piper.py`
- Modify: `ServidorDePC/test_server.py`

**Interfaces:**
- Produces: `float_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes`; `tts_elena.synthesize_wav(text, timeout_s=6.0, communicate_factory=None, decode_mp3=None) -> bytes`; `PiperEngine.load()/synthesize()/ready`

- [ ] **Step 1: Tests RED** WAV RIFF; Elena con FakeCommunicate; timeout; Piper fake voice.
- [ ] **Step 2: Implementar.**
- [ ] **Step 3: Tests PASS.**

### Task 3: `TtsEngine` fachada y borrar CosyVoice

**Files:**
- Modify: `ServidorDePC/tts_engine.py`
- Modify: `ServidorDePC/config.py` (quitar CosyVoice paths)
- Delete: `ServidorDePC/probe_cosyvoice.py`
- Modify: `ServidorDePC/test_server.py` (routing + sacar TestCosyVoicePrompt)

- [ ] **Step 1: Tests RED** prefer false no llama Elena; Elena OK; Elena fail → Piper; empty → b"".
- [ ] **Step 2: Reescribir `tts_engine.py`. Borrar probe y helpers CosyVoice.**
- [ ] **Step 3: Tests PASS.**

### Task 4: Deps, run.ps1, gitignore

**Files:**
- Modify: `ServidorDePC/requirements-tts.txt`
- Modify: `ServidorDePC/run.ps1`
- Modify: `ServidorDePC/.gitignore`
- Modify: `ServidorDePC/test_server.py` (requirements assertions)

- [ ] **Step 1: Tests RED** requirements tiene piper-tts y edge-tts, no cosyvoice/chatterbox/wetext; run.ps1 no clona CosyVoice.
- [ ] **Step 2: Implementar archivos.**
- [ ] **Step 3: `py -3.12 -m unittest test_server.py` PASS. `pip install -r requirements-tts.txt`.**
- [ ] **Step 4: No commit.**
