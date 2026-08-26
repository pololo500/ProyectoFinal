# Check-in cuento + memoria LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Check-in “¿Seguimos?” entre bloques, pregunta de reflexión al final, 10 turnos de memoria en todo TEO, card Ahora con Play/Stop del cuento.

**Architecture:** `StoryEngine` emite un chunk por turno; `AudioWorker` arma un timer de 6 s. `ConversationMemory` único. Status + `/api/stories/play|stop`. Inicio lee `currently_reading`.

**Tech Stack:** Python 3.11, llama-cpp / Groq, Android Kotlin.

## Global Constraints

- Silencio 6 s = seguir. No/basta = parar. PDF sin reescribir.
- 10 conversaciones (20 mensajes). `n_ctx=2048`.
- Misma card Inicio. Sin commit salvo pedido. Trabajar en `main`.

## Tasks

1. `conversation_memory.py` + tests; cablear FallbackLLM y CloudLLM (`history=`), `n_ctx=2048`.
2. Reescribir `StoryEngine` (checking_in / reflecting / un chunk) + `test_stories.py`.
3. `AudioWorker`: hablar un chunk, timer, reflexión LLM, registrar memoria; `api_server` + `app.py` play/stop/status.
4. Android: card Ahora, Play/Stop cuento.

Ver spec `docs/superpowers/specs/2026-08-26-cuento-checkin-memoria-design.md`.
