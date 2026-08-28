# Mute de intents LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El LLM apaga/prende intents con tags; con mute, las respuestas del nene van al LLM salvo veo veo/PPT que arrancan el motor; log de cada cambio; catálogo de juegos real.

**Architecture:** `IntentMute` en `session_policy.py` guarda el flag. `AudioWorker` omite el dispatcher si está muteado, salvo keyword de juego. Tags `[INTENTS_OFF]`/`[INTENTS_ON]` se parsean como el resto de skills. Failsafe a 3 turnos.

**Tech Stack:** Python 3.11, unittest, `fallback_llm._SYSTEM_PROMPT` (Groq lo reusa).

## Global Constraints

- Tags no se dicen en voz alta (`_strip_unspeakable`).
- Con mute: no dispatcher. Excepción: `play_veo_veo` y `play_piedra_papel` → motor + ON.
- `NOTIFY_PARENT` fuerza ON (`reason=notify_parent`).
- Failsafe: 3 turnos que **empezaron** muteados y siguen muteados → ON.
- Log solo si el flag cambia. `reason` ∈ `llm_tag` | `game_keyword` | `failsafe` | `notify_parent`.
- Juegos a ofrecer: veo veo y piedra-papel-tijera; se puede mencionar música o cuento. Sin “inventamos uno”.
- Sin commit salvo pedido de Teo. TDD: test rojo antes de producción.

## Files

- Create: `ProyectoParaRasperrypiV5/test_intent_mute.py`
- Modify: `ProyectoParaRasperrypiV5/session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`AudioWorker.__init__`, `_handle_segment`, `_ACTION_TAG_RE`, `_execute_actions`)
- Modify: `ProyectoParaRasperrypiV5/fallback_llm.py` (`_SYSTEM_PROMPT`)
- Modify: `ProyectoParaRasperrypiV5/intent_rules.json` (`play_generic`, `activity_offer`)
- Modify: `ProyectoParaRasperrypiV5/test_llm_story_guard.py`

---

### Task 1: IntentMute + helpers

**Files:**
- Create: `ProyectoParaRasperrypiV5/test_intent_mute.py`
- Modify: `ProyectoParaRasperrypiV5/session_policy.py`

**Produces:**
- `should_run_intent_dispatcher(muted: bool) -> bool`
- `game_keyword_while_muted(muted: bool, keyword: str | None) -> str | None`
- `class IntentMute` with `is_muted`, `turns_while_muted`, `apply_tag(on, reason, child_text="")`, `note_game_keyword(child_text)`, `note_child_turn_still_muted(child_text="")`, `reset()`
- `apply_llm_intent_actions(mute, actions, child_text="")` — último INTENTS_* gana; NOTIFY_PARENT fuerza ON
- `MUTE_FAILSAFE_TURNS = 3`

- [x] **Step 1: Write failing tests** in `test_intent_mute.py` (helpers, tag last-wins, log once, failsafe, game keyword).
- [x] **Step 2: Run** `python -m unittest test_intent_mute` from `ProyectoParaRasperrypiV5`. Expected: FAIL (import error).
- [x] **Step 3: Implement** `IntentMute` and helpers in `session_policy.py`.
- [x] **Step 4: Re-run tests.** Expected: PASS.

### Task 2: Prompt + copy enlatada

- [x] **Step 1: Extend** `test_llm_story_guard.py` and JSON copy asserts in `test_intent_mute.py`.
- [x] **Step 2: Run.** Expected: FAIL on missing prompt strings / “inventamos”.
- [x] **Step 3: Update** `_SYSTEM_PROMPT` and `intent_rules.json`.
- [x] **Step 4: Re-run.** Expected: PASS.

### Task 3: Cablear AudioWorker

- [x] **Step 1: Test** `AudioWorker._ACTION_TAG_RE` matches INTENTS_OFF/ON (class attr, sin instanciar el worker).
- [x] **Step 2: Run.** Expected: FAIL until regex updated.
- [x] **Step 3: Wire** mute in `_handle_segment`, tags, failsafe al cierre del turno, `_execute_actions` no-op de voz para esos tags.
- [x] **Step 4: Run** `test_intent_mute`, `test_llm_story_guard`, `test_session_policy`. Expected: PASS.

Ver spec `docs/superpowers/specs/2026-08-28-intent-mute-llm-design.md`.
