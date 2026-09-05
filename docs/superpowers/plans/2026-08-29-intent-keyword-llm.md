# Keyword-only intents + LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El dispatcher solo dispara skills por keyword (más “llama a mamá/papá”); el resto va al LLM, que avisa al padre solo con `[NOTIFY_PARENT]`.

**Architecture:** `IntentDispatcher.dispatch` deja de puntuar MiniLM/spaCy. Keyword (`is_clear_keyword_intent`) → intent enlatado conf 0.92. Si no → `unknown` (el `AudioWorker` ya manda eso al LLM). No se carga `SentenceTransformer`. El prompt prohíbe avisar por palabra suelta.

**Tech Stack:** Python 3.11, unittest, `session_policy.is_clear_keyword_intent`, `fallback_llm._SYSTEM_PROMPT`, `intent_rules.json` (solo respuestas enlatadas de keywords).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-29-intent-keyword-llm-design.md`.
- Keywords v1: las de `is_clear_keyword_intent` (no ampliar regex).
- `identity_name` se evalúa antes que `call_parent` (ya es así; no invertir el orden).
- Auto-notify de `AudioWorker` en `call_parent` no se toca.
- Mute `[INTENTS_OFF]` no se toca.
- No reescribir ni borrar entradas de `intent_rules.json`.
- TDD: test rojo antes de producción.
- Sin commit salvo pedido de Teo (omitir todos los `git commit` de este plan).
- Plataforma: Windows + Raspberry Pi 5 8 GB, CPU only.

## Files

- Create: `ProyectoParaRasperrypiV5/test_intent_keyword_route.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`IntentDispatcher.__init__`, `_load_sentence_model`, `_load_spacy_model`, `_precompute_examples`, `dispatch`)
- Modify: `ProyectoParaRasperrypiV5/fallback_llm.py` (`_SYSTEM_PROMPT`)
- Modify: `ProyectoParaRasperrypiV5/test_llm_story_guard.py`
- Modify: `ProyectoParaRasperrypiV5/test_intent_accuracy.py`
- Modify: `ProyectoParaRasperrypiV5/tests/audio_frases/manifest.json`
- Modify: `ProyectoParaRasperrypiV5/Agents.md`

No modificar: `session_policy.py` (regex), `AudioWorker` notify, `intent_rules.json`.

---

### Task 1: Ruteo keyword-or-unknown (sin MiniLM)

**Files:**
- Create: `ProyectoParaRasperrypiV5/test_intent_keyword_route.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`IntentDispatcher`, aprox. líneas 151–356)

**Interfaces:**
- Consumes: `is_clear_keyword_intent(text: str) -> str | None` en `session_policy.py` (sin cambios). `intent_rules.json` para copy enlatada.
- Produces: `IntentDispatcher.dispatch(text: str, emotion: dict | None = None) -> dict` con `intent_name`, `confidence`, `response`, y `pilar` si no es unknown. Keyword → conf `0.92` (salvo `stop_music_request`, que sigue en `0.95`). Sin keyword → `unknown`, conf `0.0`, `response=""`. `_sentence_model is None`. No importar `sentence_transformers` al construir.

- [x] **Step 1: Write the failing test**

Crear `ProyectoParaRasperrypiV5/test_intent_keyword_route.py`:

```python
"""Dispatcher: solo keywords; el resto unknown (sin MiniLM)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import IntentDispatcher

_RULES = Path(__file__).resolve().parent / "intent_rules.json"


def _dispatcher() -> IntentDispatcher:
    data = json.loads(_RULES.read_text(encoding="utf-8"))
    d = IntentDispatcher.__new__(IntentDispatcher)
    d.intents = data
    d.nlp = None
    d._sentence_model = None
    d._example_docs = {}
    d._example_embeddings = {}
    d._last_canned = {}
    d.current_emotion = None
    return d


class TestKeywordOrUnknown(unittest.TestCase):
    def setUp(self) -> None:
        self.d = _dispatcher()

    def test_zanahoria_unknown(self) -> None:
        self.assertEqual(self.d.dispatch("Zanahoria.")["intent_name"], "unknown")

    def test_bichito_unknown(self) -> None:
        self.assertEqual(
            self.d.dispatch("Encontré un bichito en el jardín.")["intent_name"],
            "unknown",
        )

    def test_hola_unknown(self) -> None:
        self.assertEqual(self.d.dispatch("hola")["intent_name"], "unknown")

    def test_me_duele_unknown(self) -> None:
        self.assertEqual(self.d.dispatch("me duele la panza")["intent_name"], "unknown")

    def test_quiero_a_mama_unknown(self) -> None:
        out = self.d.dispatch("quiero a mama")
        self.assertEqual(out["intent_name"], "unknown")

    def test_llama_a_mama_call_parent(self) -> None:
        out = self.d.dispatch("llama a mama")
        self.assertEqual(out["intent_name"], "call_parent")
        self.assertGreaterEqual(out["confidence"], 0.92)
        self.assertTrue(str(out.get("response") or "").strip())

    def test_hablar_con_papa_call_parent(self) -> None:
        self.assertEqual(
            self.d.dispatch("quiero hablar con papa")["intent_name"],
            "call_parent",
        )

    def test_como_te_llamas_no_es_call_parent(self) -> None:
        out = self.d.dispatch("como te llamas")
        self.assertEqual(out["intent_name"], "identity_name")
        self.assertNotEqual(out["intent_name"], "call_parent")

    def test_veo_veo_skill(self) -> None:
        self.assertEqual(
            self.d.dispatch("juguemos veo veo")["intent_name"],
            "play_veo_veo",
        )


class TestNoMinilmLoad(unittest.TestCase):
    def test_from_file_no_carga_minilm(self) -> None:
        d = IntentDispatcher.from_file(_RULES)
        self.assertIsNone(d._sentence_model)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `ProyectoParaRasperrypiV5`):

```bash
python -m unittest test_intent_keyword_route -v
```

Expected: FAIL. Hoy `"Zanahoria."` / `"hola"` / `"me duele la panza"` no son `unknown` (MiniLM elige `body_hurt`, `greeting`, etc.). `from_file` deja `_sentence_model` no-None si el paquete está instalado.

- [ ] **Step 3: Write minimal implementation**

En `workers.py`, clase `IntentDispatcher`:

1. `_load_sentence_model` no importa ni carga MiniLM:

```python
    def _load_sentence_model(self) -> Any:
        return None
```

2. `_load_spacy_model` no carga spaCy (dispatch ya no puntúa similitud; ahorra RAM en la Pi):

```python
    def _load_spacy_model(self):
        return None
```

3. `_precompute_examples` no encodea ni crea docs spaCy. Dejar el método como no-op que vacía los dicts, o un cuerpo que solo asigna listas vacías por intent. No llamar a `SentenceTransformer.encode`.

4. Reemplazar el cuerpo de `dispatch` **después** del early-return de texto vacío y del bloque especial `stop_music_request`, para que **no** llame `_score_intents`. Flujo:

```python
        keyword_intent = self._keyword_intent(candidate_text)
        if keyword_intent == "stop_music_request":
            # bloque existente sin cambios (conf 0.95, "Listo, paro la música.")
            ...

        if keyword_intent and keyword_intent in self.intents:
            intent_definition = self.intents[keyword_intent]
            result = {
                "intent_name": keyword_intent,
                "confidence": 0.92,
                "response": self._pick_response(
                    keyword_intent, intent_definition.get("response", "")
                ),
                "pilar": intent_definition.get("pilar", "general"),
            }
            if _dlog:
                _dlog.log_output(
                    "INTENT_DISPATCH",
                    f"intent={keyword_intent} conf=0.920 top2=0.000",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return result

        if _dlog:
            _dlog.log_output(
                "INTENT_DISPATCH",
                "unknown",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )
        return {
            "intent_name": "unknown",
            "confidence": 0.0,
            "response": "",
        }
```

No borrar `_score_intents` / `_encode_query` / `_utterance_too_thin` en v1 (los usa `test_intent_canned.py`). `dispatch` no debe llamarlos.

Dejar `_keyword_intent` como está (`return is_clear_keyword_intent(text)`).

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_intent_keyword_route test_intent_canned test_session_policy test_intent_mute -v
```

Expected: PASS. `test_intent_canned` sigue usando `_pick_response` y `_utterance_too_thin` sobre una instancia `__new__`.

- [ ] **Step 5: Commit**

Omitir. Teo no pidió commit.

---

### Task 2: Prompt — cuándo avisar al padre

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_llm_story_guard.py` (clase `TestSystemPromptNoStoryTemplate`)
- Modify: `ProyectoParaRasperrypiV5/fallback_llm.py` (`_SYSTEM_PROMPT`, el párrafo de `[NOTIFY_PARENT:razón]`)

**Interfaces:**
- Consumes: `_SYSTEM_PROMPT: str` en `fallback_llm.py` (Groq ya lo importa).
- Produces: el mismo string, más reglas de cuándo **no** avisar. Tags `[NOTIFY_PARENT]` / `[INTENTS_ON]` siguen existiendo.

- [x] **Step 1: Write the failing test**

En `test_llm_story_guard.py`, dentro de `TestSystemPromptNoStoryTemplate`, agregar:

```python
    def test_notify_solo_pedido_o_crisis(self) -> None:
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("[notify_parent", folded)
        self.assertIn("palabra suelta", folded)
        self.assertTrue(
            "no avises" in folded or "no uses [notify_parent]" in folded,
            _SYSTEM_PROMPT,
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_llm_story_guard.TestSystemPromptNoStoryTemplate.test_notify_solo_pedido_o_crisis -v
```

Expected: FAIL (`palabra suelta` no está en el prompt).

- [ ] **Step 3: Write minimal implementation**

En `_SYSTEM_PROMPT`, reemplazar las dos líneas actuales de `[NOTIFY_PARENT:razón]` por:

```python
    "- [NOTIFY_PARENT:razón] — Avisa a mamá/papá. Usalo SOLO si el nene pide hablar con mamá/papá, "
    "tiene mucho miedo, está en crisis o duele de verdad. La razón debe ser breve. "
    "NO uses [NOTIFY_PARENT] por una palabra suelta, un color, un juego, una verdura, un bicho o charla de jardín. "
    "Si no hay pedido ni crisis, respondé corto SIN el tag.\n"
```

No quitar la línea que ya dice: si pide a mamá/papá, `[NOTIFY_PARENT:razón]` **y** `[INTENTS_ON]`.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_llm_story_guard test_intent_mute -v
```

Expected: PASS (incluidos tests viejos de “no ofrezcas” / INTENTS_OFF).

- [ ] **Step 5: Commit**

Omitir.

---

### Task 3: Accuracy, corpus y Agents.md

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_intent_accuracy.py` (`CASES` y el print de backend)
- Modify: `ProyectoParaRasperrypiV5/tests/audio_frases/manifest.json` (campo `intent` de clips que ya no son keyword)
- Modify: `ProyectoParaRasperrypiV5/Agents.md` (bullets NLU y patrón de enrutamiento)

**Interfaces:**
- Consumes: `IntentDispatcher.dispatch` de Task 1.
- Produces: `CASES` alineados a keyword-or-unknown. Corpus NLU no espera `greeting` / `crisis_cry` / `body_hurt` por embeddings.

- [ ] **Step 1: Write the failing test (actualizar expectativas)**

En `test_intent_accuracy.py`, cambiar `CASES` para que todo lo que **no** es keyword espere `"unknown"`. Dejar estos expected (el texto de la izquierda no cambia):

- `hagamos yoga` / `quiero estirarme` → `yoga_request`
- `juguemos veo veo` / `veo veo` / `dale veo veo` / `jugemos veo veo` → `play_veo_veo`
- `piedra papel o tijera` / `juguemos piedra papel tijera` / `quiero jugar al Piedra, papel o tijera` → `play_piedra_papel`
- `paro la musica` → `stop_music_request`
- `como te llamas` / `quien sos` → `identity_name`
- `cantame una cancion` / `quiero musica` / `pone musica` / `cantame una cansión` → `song_request`
- `llama a mama` / `quiero hablar con papa` → `call_parent`
- `dame un abrazo` / `abrazame` → `hug_request`
- `tengo hambre` / `quiero agua` / `tengo sed` → `needs_basic`
- Todos los demás de `CASES` (hola, emociones, `quiero a mama`, `me duele la panza`, `te quiero`, `dame un abraso`, `tengo ambre`, `como se llama`, `que es eso`, etc.) → `unknown`

En `main()`, cambiar el print de backend a:

```python
    backend = "keyword" if dispatcher._sentence_model is None else "sentence-transformers"
```

En `tests/audio_frases/manifest.json`, poner `"intent": "unknown"` en clips cuyo `text` no dispara keyword. Ejemplos que **sí** se quedan: PPT, veo veo, canción, stop música, `llama a mama`, `quiero hablar con papa`, yoga, hambre/agua, abrazo. Cambiar a `unknown`: `hola teo`, `chau teo`, `estoy triste` / `enojado` / `feliz`, `quiero a mama`, `ayudame a calmarme`, `estoy aburrido`, y en `record_also` los que esperaban `greeting` (`hola teo nene`, `ola teo`, `Hola.m4a`). `Hola me llamo Tomás` ya es `unknown`. `Llama a mama o papa tengo miedo` sigue `call_parent`.

- [ ] **Step 2: Run test to verify it fails**

Si Task 1 ya está hecha, `python test_intent_accuracy.py` debería pasar en cuanto `CASES` esté actualizado. Si alguien corre accuracy **antes** de Task 1, fallará. Orden: Task 1 → Task 3. Este step confirma el script:

```bash
python test_intent_accuracy.py
```

Expected: 100% de `CASES` OK (o el recuento `correct == len(CASES)`). Si un keyword se te escapó (p. ej. `te quiero` sigue esperado `hug_request`), FAIL → corregir expected a `unknown` (`hug` solo por regex de abrazo).

- [ ] **Step 3: Write minimal implementation (docs)**

En `Agents.md`:

- Reemplazar el bullet **Procesamiento de Lenguaje (NLU)** por: keywords en `session_policy.is_clear_keyword_intent` (juegos, cuento, música, yoga, abrazo, nombre, hambre/sed, `call_parent`). El resto → `unknown` → LLM. MiniLM no se carga.
- Reemplazar la regla 2 **Patrón de Enrutamiento**: no similitud spaCy/MiniLM para elegir intent. Dictionary dispatch solo para **respuestas enlatadas** de esos keywords. Charla libre al LLM.

No tocar `intent_rules.json`.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_intent_keyword_route test_intent_canned test_session_policy test_intent_mute test_llm_story_guard -v
python test_intent_accuracy.py
```

Expected: unittest OK; accuracy `correct == len(CASES)`.

Opcional: `python test_audio_corpus.py --nlu-only` si el script lo permite; si no, no es bloqueante.

- [ ] **Step 5: Commit**

Omitir.

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| MiniLM no rutea; no cargar SentenceTransformer | 1 |
| Keyword → canned 0.92; resto unknown | 1 |
| Excepción `call_parent` + tests llama/hablar | 1 |
| `como te llamas` no es `call_parent` | 1 |
| `quiero a mama` / zanahoria / hola / me duele → unknown | 1 |
| Prompt no avisar por palabra suelta | 2 |
| Mute / AudioWorker notify / regex sin cambios | (ninguna: no tocar) |
| `intent_rules.json` no reescribir | 3 (explícito) |
| `test_intent_accuracy` + corpus | 3 |
| Agents.md NLU | 3 |
