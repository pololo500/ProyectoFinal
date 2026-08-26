# Voz Piper Daniela AR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Piper local usa `es_AR-daniela-high` con `length_scale=1.08` y un punto final si falta, para que TEO suene más humano en la Pi 5.

**Architecture:** Sin motor nuevo. Constantes y `_prepare_tts_text` viven en `SpeechWorker`. `speak` / `speak_and_wait` normalizan el texto al encolar; `_ensure_piper_model` y `_speak_piper` leen esas constantes. Fallback SAPI/espeak-ng no cambia.

**Tech Stack:** Python 3.11, `piper-tts`, `unittest`, `sounddevice` (sin tocar).

## Global Constraints

- Raspberry Pi 5 8 GB, CPU only; no Kokoro/XTTS ni dependencias nuevas de resample.
- Modelo: `es_AR-daniela-high`; cache `~/.edge_ai_models/piper/`; no borrar `es_MX-claude-high`.
- `length_scale=1.08`, `noise_scale=0.667`, `noise_w_scale=0.90`.
- No reescribir `intent_rules.json` ni el prompt del LLM.
- No UI de voz. `CloudTTS` no se modifica; el prepare sí corre en modo nube porque vive en `speak` / `speak_and_wait`.
- Tests: `python -m unittest` desde `ProyectoParaRasperrypiV5`.
- No crear commits a menos que Teo lo pida. Si un paso dice Commit, omitirlo hasta que lo pida.

---

## File structure

- Create: `ProyectoParaRasperrypiV5/test_tts_voice.py` — unit tests de texto, modelo y `SynthesisConfig`.
- Modify: `ProyectoParaRasperrypiV5/workers.py` — `SpeechWorker` (constantes, `_prepare_tts_text`, `speak`, `speak_and_wait`, `_ensure_piper_model`, `_speak_piper`).
- Modify: `ProyectoParaRasperrypiV5/Agents.md` — documentar Daniela y los tres parámetros.
- Do not modify: `test_tts_playback.py`, `cloud_services.py`, `intent_rules.json`.

---

### Task 1: Normalizar texto TTS

**Files:**
- Create: `ProyectoParaRasperrypiV5/test_tts_voice.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`SpeechWorker._strip_tts_markup` ~2363, `speak` ~2368, `speak_and_wait` ~2381)

**Interfaces:**
- Consumes: `SpeechWorker._strip_tts_markup(text: str) -> str` (ya existe)
- Produces: `SpeechWorker._prepare_tts_text(text: str) -> str` (staticmethod). `speak` y `speak_and_wait` encolan ` _prepare_tts_text(_strip_tts_markup(...)) `.

- [ ] **Step 1: Write the failing tests**

Crear `ProyectoParaRasperrypiV5/test_tts_voice.py`:

```python
"""Tests de voz Piper (texto, modelo, parámetros)."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from workers import SpeechWorker


class TestPrepareTtsText(unittest.TestCase):
    def test_agrega_punto_si_falta(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola"), "hola.")

    def test_no_toca_exclamacion(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("¡Hola!"), "¡Hola!")

    def test_no_toca_pregunta(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("¿Todo bien?"), "¿Todo bien?")

    def test_no_toca_puntos_suspensivos(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola…"), "hola…")

    def test_colapsa_espacios(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola   che"), "hola che.")

    def test_vacio_sigue_vacio(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text(""), "")
        self.assertEqual(SpeechWorker._prepare_tts_text("   "), "")

    def test_speak_encola_texto_preparado(self) -> None:
        worker = SpeechWorker()
        worker.speak("hola")
        self.assertEqual(worker._queue.get_nowait(), "hola.")

    def test_speak_no_encola_si_solo_habia_markup(self) -> None:
        worker = SpeechWorker()
        worker.speak("  [DALE]  ")
        self.assertTrue(worker._queue.empty())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `ProyectoParaRasperrypiV5`):

```bash
python -m unittest test_tts_voice.py -v
```

Expected: FAIL con `AttributeError: type object 'SpeechWorker' has no attribute '_prepare_tts_text'`.

- [ ] **Step 3: Write minimal implementation**

En `workers.py`, agregar este staticmethod **justo debajo** de `_strip_tts_markup`:

```python
    @staticmethod
    def _prepare_tts_text(text: str) -> str:
        cleaned = re.sub(r"\s{2,}", " ", text).strip()
        if not cleaned:
            return ""
        if cleaned[-1] not in ".!?…":
            cleaned += "."
        return cleaned
```

Reemplazar el cuerpo de `speak` para preparar después del strip:

```python
    def speak(self, text: str) -> None:
        speech_text = self._prepare_tts_text(self._strip_tts_markup((text or "").strip()))
        if not speech_text:
            return
        try:
            self._queue.put_nowait(speech_text)
            log_action("SpeechWorker", f"enqueued TTS ({len(speech_text)} chars)")
        except queue.Full:
            log_action("SpeechWorker", "cola TTS llena, se descarta frase")
```

Reemplazar el arranque de `speak_and_wait` igual (el resto del método no cambia):

```python
    def speak_and_wait(self, text: str, timeout: float = 30.0) -> None:
        """Queue text for speaking and block until playback finishes."""
        speech_text = self._prepare_tts_text(self._strip_tts_markup((text or "").strip()))
        if not speech_text:
            return
        self._idle_event.clear()
        try:
            self._queue.put_nowait(speech_text)
        except queue.Full:
            self._idle_event.set()
            return
        self._idle_event.wait(timeout=timeout)
```

No llamar `_prepare_tts_text` otra vez en `_speak_piper`.

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
python -m unittest test_tts_voice.py -v
```

Expected: 8 tests OK (`TestPrepareTtsText`).

- [ ] **Step 5: Commit** (omitir salvo que Teo lo pida)

```bash
git add ProyectoParaRasperrypiV5/test_tts_voice.py ProyectoParaRasperrypiV5/workers.py
git commit -m "feat(tts): puntuar frases antes de Piper para mejor prosodia"
```

---

### Task 2: Modelo Daniela y parámetros de síntesis

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_tts_voice.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`class SpeechWorker` ~2314, `_ensure_piper_model` ~2678, `_speak_piper` ~2702)
- Modify: `ProyectoParaRasperrypiV5/Agents.md` líneas 13 y 26

**Interfaces:**
- Consumes: `_prepare_tts_text` de Task 1 (no se vuelve a tocar).
- Produces: atributos de clase `SpeechWorker.PIPER_MODEL_NAME: str`, `PIPER_MODEL_HF_PATH: str`, `PIPER_LENGTH_SCALE: float`, `PIPER_NOISE_SCALE: float`, `PIPER_NOISE_W_SCALE: float`. `_ensure_piper_model()` descarga `{PIPER_MODEL_HF_PATH}/{PIPER_MODEL_NAME}`. `_speak_piper` pasa esos floats a `SynthesisConfig`.

- [ ] **Step 1: Write the failing tests**

Agregar al final de `test_tts_voice.py`, **antes** de `if __name__ == "__main__":`:

```python
class TestPiperVoiceConfig(unittest.TestCase):
    def test_modelo_es_daniela_ar_high(self) -> None:
        self.assertEqual(SpeechWorker.PIPER_MODEL_NAME, "es_AR-daniela-high")
        self.assertEqual(SpeechWorker.PIPER_MODEL_HF_PATH, "es/es_AR/daniela/high")

    def test_parametros_de_sintesis(self) -> None:
        self.assertAlmostEqual(SpeechWorker.PIPER_LENGTH_SCALE, 1.08)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_SCALE, 0.667)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_W_SCALE, 0.90)

    def test_ensure_piper_model_descarga_daniela_si_falta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            with patch.object(Path, "home", return_value=fake_home), patch(
                "workers.urllib.request.urlretrieve"
            ) as retrieve:
                path = SpeechWorker._ensure_piper_model()
            self.assertEqual(path.name, "es_AR-daniela-high.onnx")
            urls = [call.args[0] for call in retrieve.call_args_list]
            self.assertTrue(
                any("es/es_AR/daniela/high/es_AR-daniela-high.onnx" in u for u in urls)
            )
            self.assertTrue(
                any("es/es_AR/daniela/high/es_AR-daniela-high.onnx.json" in u for u in urls)
            )

    def test_ensure_piper_model_no_redescarga_si_existe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            cache = fake_home / ".edge_ai_models" / "piper"
            cache.mkdir(parents=True)
            (cache / "es_AR-daniela-high.onnx").write_bytes(b"x")
            (cache / "es_AR-daniela-high.onnx.json").write_text("{}")
            with patch.object(Path, "home", return_value=fake_home), patch(
                "workers.urllib.request.urlretrieve"
            ) as retrieve:
                path = SpeechWorker._ensure_piper_model()
            retrieve.assert_not_called()
            self.assertEqual(path, cache / "es_AR-daniela-high.onnx")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_tts_voice.py -v
```

Expected: FAIL con `AttributeError: type object 'SpeechWorker' has no attribute 'PIPER_MODEL_NAME'` (los tests de Task 1 siguen pasando).

- [ ] **Step 3: Write minimal implementation**

En `workers.py`, justo después de `class SpeechWorker:`, agregar:

```python
    PIPER_MODEL_NAME = "es_AR-daniela-high"
    PIPER_MODEL_HF_PATH = "es/es_AR/daniela/high"
    PIPER_LENGTH_SCALE = 1.08
    PIPER_NOISE_SCALE = 0.667
    PIPER_NOISE_W_SCALE = 0.90
```

Reemplazar `_ensure_piper_model` completo:

```python
    @staticmethod
    def _ensure_piper_model() -> Path:
        """Return path to the piper ONNX model, downloading it on first use."""
        model_name = SpeechWorker.PIPER_MODEL_NAME
        cache_dir = Path.home() / ".edge_ai_models" / "piper"
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_file = cache_dir / f"{model_name}.onnx"
        config_file = cache_dir / f"{model_name}.onnx.json"

        if model_file.exists() and config_file.exists():
            return model_file

        base_url = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{SpeechWorker.PIPER_MODEL_HF_PATH}/{model_name}"
        )

        for suffix, target in [(".onnx", model_file), (".onnx.json", config_file)]:
            if not target.exists():
                urllib.request.urlretrieve(f"{base_url}{suffix}", target)

        return model_file
```

Reemplazar el bloque `SynthesisConfig` dentro de `_speak_piper` (el resto del método igual):

```python
            syn_config = SynthesisConfig(
                length_scale=SpeechWorker.PIPER_LENGTH_SCALE,
                noise_scale=SpeechWorker.PIPER_NOISE_SCALE,
                noise_w_scale=SpeechWorker.PIPER_NOISE_W_SCALE,
            )
```

En `Agents.md`, reemplazar la viñeta de TTS (línea 13) por:

```markdown
- **Audio (Síntesis/TTS):** `piper-tts` (TTS neural local, modelo `es_AR-daniela-high`, `length_scale=1.08`, `noise_scale=0.667`, `noise_w_scale=0.90`). Si piper no está disponible, fallback a `System.Speech` (Windows) o `espeak-ng` (Linux).
```

En la regla 7 (línea 26), dejar el texto de recursos y dejar explícita la voz:

```markdown
7. **TTS con Voz Natural:** La respuesta de la intención detectada debe reproducirse por el parlante seleccionado con Piper `es_AR-daniela-high`. El consumo de recursos debe ser mínimo (modelo ONNX optimizado para ARM64).
```

No borrar archivos en `~/.edge_ai_models/piper/`.

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
python -m unittest test_tts_voice.py test_tts_playback.py -v
```

Expected: todos OK. `test_tts_playback.py` no debe fallar (no se tocó el playback).

- [ ] **Step 5: Verificación manual en la Pi**

En la Pi, con el entorno del proyecto:

```bash
python -c "from workers import SpeechWorker; w=SpeechWorker(); w.start(); w.speak_and_wait('¡Hola! Qué lindo que estés acá.'); w.stop()"
```

Criterio: acento argentino, menos arrastre que Claude 1.25, sin cortes. Si Piper no carga, el log debe decir `Error cargando modelo piper:` y caer a espeak (no a Claude).

- [ ] **Step 6: Commit** (omitir salvo que Teo lo pida)

```bash
git add ProyectoParaRasperrypiV5/test_tts_voice.py ProyectoParaRasperrypiV5/workers.py ProyectoParaRasperrypiV5/Agents.md
git commit -m "feat(tts): voz Piper es_AR-daniela-high con prosodia menos rígida"
```

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| Modelo `es_AR-daniela-high` + URL HF + cache | Task 2 |
| `length_scale=1.08`, `noise_scale=0.667`, `noise_w_scale=0.90` | Task 2 |
| `_prepare_tts_text` + wire en `speak`/`speak_and_wait` | Task 1 |
| No re-prepare en `_speak_piper` | Task 1 |
| Fallback SAPI/espeak, no Claude | Task 2 (sin código de fallback extra; cadena actual) |
| No borrar ONNX viejo | Task 2 |
| `Agents.md` | Task 2 |
| Unit tests modelo/URL/params/texto | Task 1 + 2 |
| `test_tts_playback.py` intacto | Task 2 step 4 |
| Verificación Pi | Task 2 step 5 |
| Fuera de alcance (B, Kokoro, intents, UI, soxr) | ningún task |
