# CosyVoice 2 TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar Chatterbox por CosyVoice 2 en `ServidorDePC` y medir una frase de Teo en escritorio.

**Architecture:** `TtsEngine` sigue exponiendo `load()` / `synthesize(text) -> bytes`. Carga CosyVoice2 desde `third_party/CosyVoice`, clona con el recorte `teo_es_ar_prompt.wav` + transcript sidecar. HTTP y la Pi no cambian.

**Tech Stack:** FunAudioLLM CosyVoice2-0.5B, PyTorch CUDA, wetext, faster-whisper ya instalado (no se usa en TTS).

## Global Constraints

- Python 3.12 (`py -3.12`). No pinear `torch==2.3.1`.
- No commit a menos que Teo lo pida.
- WAV de voces en gitignore. Repo CosyVoice y pesos en gitignore.
- Tests de server sin GPU: unittest `test_server.py`.

---

### Task 1: Prompt recortado + config + tests del motor

**Files:**
- Create: `ServidorDePC/voices/teo_es_ar_prompt.wav` (local)
- Create: `ServidorDePC/voices/teo_es_ar_prompt.txt`
- Modify: `ServidorDePC/config.py`
- Modify: `ServidorDePC/tts_engine.py`
- Modify: `ServidorDePC/test_server.py`
- Modify: `ServidorDePC/requirements-tts.txt`
- Modify: `ServidorDePC/.gitignore`
- Modify: `ServidorDePC/run.ps1`
- Modify: `ServidorDePC/voices/README.md`

**Interfaces:**
- Consumes: `TTS_VOICE_PATH`, `TTS_PROMPT_TEXT`
- Produces: `TtsEngine.load/synthesize`, `_read_prompt_text() -> str`, `_concat_speech(chunks) -> np.ndarray`

- [ ] **Step 1: Write failing tests** for prompt vacío, concat de chunks, requirements-tts sin chatterbox.
- [ ] **Step 2: Run tests, confirm RED**
- [ ] **Step 3: Crop WAV 1.28–6.06s, sidecar txt, tts_engine CosyVoice2, gitignore, run.ps1**
- [ ] **Step 4: Run `py -3.12 -m unittest test_server.py` — GREEN**
- [ ] **Step 5: Skip commit** (Teo no lo pidió)

### Task 2: Instalar CosyVoice + Torch CUDA + probe de escritorio

**Files:**
- Create: `ServidorDePC/probe_cosyvoice.py`
- Create (clone): `ServidorDePC/third_party/CosyVoice`
- Create (download): `ServidorDePC/pretrained_models/CosyVoice2-0.5B`

- [ ] **Step 1:** `git clone --recursive` CosyVoice
- [ ] **Step 2:** Reinstalar `torch`/`torchaudio` CUDA (cu128 luego cu124). Verificar `torch.cuda.is_available()`.
- [ ] **Step 3:** `pip install -r requirements-tts.txt` sin tocar el pin de torch.
- [ ] **Step 4:** Descargar `FunAudioLLM/CosyVoice2-0.5B`
- [ ] **Step 5:** `py -3.12 probe_cosyvoice.py` con la frase de Holi; reportar ms y reproducir WAV.
