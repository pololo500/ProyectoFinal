# Filtro habla débil + confianza STT — plan

> **For agentic workers:** ejecutar inline en esta sesión (Teo pidió implementación). TDD. No commit salvo que lo pida.

**Goal:** No mandar a Whisper/LLM clips con &lt; 300 ms de hops ≥ 7 %, y recortar alucinaciones con `no_speech` / `logprob` también en el STT de la PC.

**Architecture:** predicados puros en `session_policy`; medición de hops en `workers`; el servidor PC agrega confianza al JSON; el cliente la mapea a `TranscriptionResult`; `low_confidence` sale en silencio.

**Tech Stack:** Python 3.12, unittest, faster-whisper en la PC.

## Global Constraints

- Piso de volumen sigue en 7 %. Mínimo activo = 0,30 s.
- Descarte = silencio (sin TTS de retry).
- No denylist de «qué pasa».
- PowerShell sin `&&`. No arrancar `app.py` en la Pi.
- SFTP a la Pi los `.py` del robot; ServidorDePC corre en Windows.

---

### Task 1: predicados puros

**Files:**
- Modify: `ProyectoParaRasperrypiV5/session_policy.py`
- Test: `ProyectoParaRasperrypiV5/test_session_policy.py`

- [x] Test `skip_stt_for_weak_speech(0.29)` True, `(0.30)` False
- [x] Test `stt_is_low_confidence` no_speech 0.76 True, 0.75 False; logprob -0.91 True
- [x] Implementar constantes y funciones
- [x] unittest

### Task 2: active_speech_seconds + gate pre-STT

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py`
- Test: `ProyectoParaRasperrypiV5/test_mic_input.py`

- [x] Test: 40 ms de hops a 10 % + resto 2 % → skip True; 400 ms a 10 % → skip False
- [x] `active_speech_seconds` con hops 20 ms @ 16 kHz
- [x] `_handle_segment` llama skip **antes** de `_remote_or_local_stt`; log y return
- [x] unittest

### Task 3: PC STT devuelve confianza

**Files:**
- Modify: `ServidorDePC/stt_engine.py`, `ServidorDePC/handlers.py`
- Test: `ServidorDePC/test_server.py`
- Modify: `ProyectoParaRasperrypiV5/pc_server_client.py`, `workers.py`
- Test: `ProyectoParaRasperrypiV5/test_pc_stt_llm_route.py`

- [x] handle_transcribe incluye `avg_logprob` / `no_speech_prob` si el engine los da
- [x] cliente + `_remote_or_local_stt` arman `TranscriptionResult` con `stt_is_low_confidence`
- [x] `low_confidence` no habla «No te escuché»; return silencioso
- [x] unittest Pi + PC

### Task 4: SFTP Pi

- [x] Subir `session_policy.py`, `workers.py`, `pc_server_client.py` y tests del robot
- [x] Avisar: reiniciar `app.py` **y** el servidor Windows (`server.py`)
