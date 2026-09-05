# Latencia hasta la primera voz (opción A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (esta sesión; Teo pidió implementar). TDD. Sin `git commit` salvo pedido de Teo.

**Goal:** Bajar el silencio post-STT (hola/chau sin LLM, Whisper `beam_size=1`, `n_ctx=1024`, 4 turnos) con el system prompt que Teo fijó, y palancas de rollback por env.

**Architecture:** Keywords de saludo/despedida son match de frase entera en `is_clear_keyword_intent`. Límites de Whisper/LLM/memoria se leen de env con defaults nuevos. El prompt largo se actualiza in-place (no compacto). Streaming TTS queda fuera (fase 2).

**Tech Stack:** Python 3.11, unittest, `session_policy`, `workers.AudioWorker`, `fallback_llm`, `conversation_memory`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-30-latencia-silencio-pre-tts-design.md`.
- Whisper **sigue `medium`**. Solo `beam_size` 5→1. Override `WHISPER_BEAM=5`.
- Prompt: el texto de Teo (3–7 años, `[NOTIFY_PARENT:razón explicandole al padre]`, CALM si se despide). No el compacto 2–4.
- Greeting/farewell: frase **entera** (p. ej. `hola me llamo tomas` → unknown).
- Fase 2 streaming LLM→Piper: no implementar.
- TDD: test rojo antes de producción.
- Sin commit salvo pedido de Teo.
- Plataforma: Windows + Raspberry Pi 5 8 GB, CPU only.

## Files

- Modify: `ProyectoParaRasperrypiV5/session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`whisper_beam_size`, `transcribe`)
- Modify: `ProyectoParaRasperrypiV5/fallback_llm.py` (`_SYSTEM_PROMPT`, `llm_n_ctx`)
- Modify: `ProyectoParaRasperrypiV5/conversation_memory.py`
- Modify: `ProyectoParaRasperrypiV5/test_session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/test_intent_keyword_route.py`
- Modify: `ProyectoParaRasperrypiV5/test_intent_accuracy.py`
- Modify: `ProyectoParaRasperrypiV5/test_llm_story_guard.py`
- Create: `ProyectoParaRasperrypiV5/test_latencia_a.py`
- Modify: `ProyectoParaRasperrypiV5/tests/audio_frases/manifest.json`
- Modify: `ProyectoParaRasperrypiV5/Agents.md`
- Modify: `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md`
- Modify: `docs/superpowers/specs/2026-08-30-latencia-silencio-pre-tts-design.md`

---

### Task 1: Greeting/farewell por frase entera

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/test_intent_keyword_route.py`
- Modify: `ProyectoParaRasperrypiV5/test_intent_accuracy.py`
- Modify: `ProyectoParaRasperrypiV5/tests/audio_frases/manifest.json`

**Interfaces:**
- Consumes: `_normalize(text: str) -> str`
- Produces: `is_clear_keyword_intent("hola") == "greeting"`; `is_clear_keyword_intent("chau") == "farewell"`; `is_clear_keyword_intent("hola me llamo tomas") is None`

- [x] **Step 1: Write the failing tests** in `test_session_policy.py` (class `TestMicHalfDuplex.test_keywords_claros` plus new class `TestGreetingFarewellExact`).

- [x] **Step 2: Run to verify fail**

- [x] **Step 3: Implement** phrase-key + frozensets in `is_clear_keyword_intent` (después de `_normalize`, antes de PPT).

- [x] **Step 4: Update tests that expected `hola`/`chau` → unknown.** Run accuracy + keyword route.

- [x] **Step 5: Skip commit**

---

### Task 2: Whisper beam_size=1 + env

**Files:**
- Create/modify: `test_latencia_a.py`
- Modify: `workers.py`

- [ ] Failing test: default 1, `WHISPER_BEAM=5` → 5
- [ ] Implement `whisper_beam_size()`; `transcribe(..., beam_size=whisper_beam_size())`

---

### Task 3: n_ctx=1024 + env

- [ ] Failing test `llm_n_ctx()` default 1024, `LLM_N_CTX=2048` → 2048
- [ ] Wire `Llama(n_ctx=llm_n_ctx())`

---

### Task 4: Memoria 4 turnos + env

- [ ] Failing test default 4 (8 messages); `CONVO_MAX_TURNS=10` → 10
- [ ] `ConversationMemory.__init__` lee env si `max_turns is None`

---

### Task 5: Prompt de Teo

- [ ] Tests: `Piedra Papel o Tijera`, `explicandole al padre`, `despide` en `_SYSTEM_PROMPT`
- [ ] Replace `_SYSTEM_PROMPT` with Teo's text
- [ ] Keep previous wording in spec/LATENCIA as rollback of copy (not env)

---

### Task 6: Docs rollback

- [ ] `LATENCIA_AUDIO_CAMARA.md` sección 2026-08-30
- [ ] `Agents.md` beam 1, n_ctx 1024, 4 turnos, greeting/farewell keywords
- [ ] Spec: prompt real (no compacto 2–4)
