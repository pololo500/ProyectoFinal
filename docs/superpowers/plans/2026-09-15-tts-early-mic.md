# Micrófono 0,5 s antes del fin del TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD. Sin `git commit` salvo pedido de Teo.

**Goal:** En TTS conversacional, el micrófono empieza a encolar 0,50 s antes de que el parlante termine, y esa cola no se tira ni se tapa con eco de 0,40 s.

**Architecture:** Predicado puro `tts_blocks_mic` en `session_policy.py`. `SpeechWorker` expone remaining del OutputStream y `tts_blocks_mic()`; `is_busy()` no cambia. `AudioWorker` usa ese predicado para half-duplex, desmutea antes del TTS conversacional, y no drena la cola al terminar esa frase.

**Tech Stack:** Python 3.11, `unittest` (`python test_*.py` desde `ProyectoParaRasperrypiV5`).

**Spec:** `docs/superpowers/specs/2026-09-15-tts-early-mic-design.md`

## Global Constraints

- `MIC_EARLY_OPEN_SECONDS = 0.50`. El mic de TTS conversacional abre si `remaining_s <= 0.50`.
- `ECHO_MUTE_SECONDS` sigue `0.40` para **música y cuento**. Tras TTS conversacional: `_echo_mute_until = 0.0` y **no** drain.
- Música (`is_music`) y cuento (`is_story` / `_pipeline_active` / `_story_pipeline_active`): el mic permanece cerrado hasta `remaining == 0`.
- Mientras Piper/PC sintetiza (`remaining_s is None` y está speaking): el mic sigue cerrado.
- `SpeechWorker.is_busy()` no cambia: sigue `True` hasta el último sample.
- Whisper/LLM siguen con captura muteada. Solo se desmutea al entrar a `speak_and_wait(..., story=False)`.
- TDD: test rojo **antes** de producción. unittest, **no pytest**.
- Sin commit salvo pedido de Teo (omitir todos los `git commit`).
- Tras cambios de producción en `session_policy.py` / `workers.py`: subir con `uploading-to-raspberry-pi`. `PI_HOST=192.168.0.148`, `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. **NUNCA** arrancar `app.py` salvo que Teo lo pida.
- PowerShell: no `&&`. Clave solo en `$env:PI_SSH_PASS` de esa invocación.

---

## File structure

- Modify: `ProyectoParaRasperrypiV5/session_policy.py` — `MIC_EARLY_OPEN_SECONDS`, `tts_remaining_seconds`, `tts_blocks_mic`, `keep_audio_queue_after_tts`.
- Modify: `ProyectoParaRasperrypiV5/test_session_policy.py` — tests puros de esos helpers.
- Modify: `ProyectoParaRasperrypiV5/workers.py` — `SpeechWorker` remaining/`tts_blocks_mic()`; `AudioWorker` half-duplex, unmute, no-drain.
- Modify: `ProyectoParaRasperrypiV5/test_tts_playback.py` — `SpeechWorker.tts_blocks_mic` vs `is_busy`.
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py` — wiring de captura / no-drain conversacional.

No tocar `alsa_capture.py` (sigue llamando `speaker_busy()`). No AEC. No barge-in.

---

### Task 1: Predicados puros de overlap

**Files:**
- Modify: `ProyectoParaRasperrypiV5/session_policy.py` (después de `ECHO_MUTE_SECONDS`, ~línea 181)
- Test: `ProyectoParaRasperrypiV5/test_session_policy.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `MIC_EARLY_OPEN_SECONDS: float = 0.50`
  - `tts_remaining_seconds(now: float, playback_end: float | None, *, speaking: bool) -> float | None`
  - `tts_blocks_mic(remaining_s: float | None, *, is_music: bool = False, is_story: bool = False) -> bool`
  - `keep_audio_queue_after_tts(*, is_music: bool, is_story: bool) -> bool`

- [ ] **Step 1: Write the failing tests**

En `test_session_policy.py`, agregar al import de `session_policy`:

```python
    keep_audio_queue_after_tts,
    tts_blocks_mic,
    tts_remaining_seconds,
```

Después de `class TestMicHalfDuplex`, agregar:

```python
class TestTtsEarlyMic(unittest.TestCase):
    def test_sintetizando_bloquea(self) -> None:
        self.assertIsNone(tts_remaining_seconds(10.0, None, speaking=True))
        self.assertTrue(tts_blocks_mic(None, is_music=False, is_story=False))

    def test_idle_remaining_cero(self) -> None:
        self.assertEqual(tts_remaining_seconds(10.0, 12.0, speaking=False), 0.0)
        self.assertFalse(tts_blocks_mic(0.0, is_music=False, is_story=False))

    def test_abre_en_punto_cinco(self) -> None:
        self.assertTrue(tts_blocks_mic(0.51, is_music=False, is_story=False))
        self.assertFalse(tts_blocks_mic(0.50, is_music=False, is_story=False))
        self.assertFalse(tts_blocks_mic(0.10, is_music=False, is_story=False))

    def test_musica_y_cuento_bloquean_el_tail(self) -> None:
        self.assertTrue(tts_blocks_mic(0.10, is_music=True, is_story=False))
        self.assertTrue(tts_blocks_mic(0.10, is_music=False, is_story=True))

    def test_keep_queue_solo_conversacional(self) -> None:
        self.assertTrue(keep_audio_queue_after_tts(is_music=False, is_story=False))
        self.assertFalse(keep_audio_queue_after_tts(is_music=True, is_story=False))
        self.assertFalse(keep_audio_queue_after_tts(is_music=False, is_story=True))
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `ProyectoParaRasperrypiV5`):

```
python test_session_policy.py TestTtsEarlyMic
```

Expected: `ImportError: cannot import name 'tts_blocks_mic'`

- [ ] **Step 3: Write minimal implementation**

En `session_policy.py`, inmediatamente después de `ECHO_MUTE_SECONDS = 0.40`:

```python
MIC_EARLY_OPEN_SECONDS = 0.50


def tts_remaining_seconds(
    now: float, playback_end: float | None, *, speaking: bool
) -> float | None:
    if not speaking:
        return 0.0
    if playback_end is None:
        return None
    return max(0.0, float(playback_end) - float(now))


def tts_blocks_mic(
    remaining_s: float | None, *, is_music: bool = False, is_story: bool = False
) -> bool:
    if is_music or is_story:
        return remaining_s is None or remaining_s > 0.0
    if remaining_s is None:
        return True
    return remaining_s > MIC_EARLY_OPEN_SECONDS


def keep_audio_queue_after_tts(*, is_music: bool, is_story: bool) -> bool:
    return not is_music and not is_story
```

- [ ] **Step 4: Run test to verify it passes**

```
python test_session_policy.py TestTtsEarlyMic
```

Expected: `OK` (5 tests). Luego `python test_session_policy.py` completo: `OK`.

---

### Task 2: `SpeechWorker.tts_blocks_mic`

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`SpeechWorker.__init__` ~3933, `is_busy` ~3953, `interrupt_playback` ~3997, `speak_and_wait` ~4067, `_play_wav_via_output_stream` ~4231, `_speak_sentence_pipeline` ~4523)
- Test: `ProyectoParaRasperrypiV5/test_tts_playback.py`

**Interfaces:**
- Consumes: `tts_remaining_seconds`, `tts_blocks_mic` de Task 1
- Produces:
  - `SpeechWorker._tts_playback_end: float | None`
  - `SpeechWorker._tts_is_story: bool`
  - `SpeechWorker.tts_remaining_seconds(self) -> float | None`
  - `SpeechWorker.tts_blocks_mic(self) -> bool`
  - `is_busy()` invariante

- [ ] **Step 1: Write the failing tests**

Al final de `test_tts_playback.py`, antes de `if __name__`:

```python
class TestTtsBlocksMic(unittest.TestCase):
    def test_is_busy_sigue_true_en_el_tail(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker._idle_event.clear()
        worker._tts_playback_end = __import__("time").monotonic() + 0.10
        self.assertTrue(worker.is_busy())
        self.assertFalse(worker.tts_blocks_mic())

    def test_sintetizando_bloquea_el_mic(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker._idle_event.clear()
        worker._tts_playback_end = None
        self.assertTrue(worker.tts_blocks_mic())

    def test_musica_bloquea_en_el_tail(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker._idle_event.clear()
        worker._is_playing_music = True
        worker._tts_playback_end = __import__("time").monotonic() + 0.10
        self.assertTrue(worker.tts_blocks_mic())

    def test_cuento_bloquea_en_el_tail(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker._idle_event.clear()
        worker._tts_is_story = True
        worker._tts_playback_end = __import__("time").monotonic() + 0.10
        self.assertTrue(worker.tts_blocks_mic())

    def test_idle_no_bloquea(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        self.assertTrue(worker._idle_event.is_set())
        self.assertFalse(worker.tts_blocks_mic())
        self.assertFalse(worker.is_busy())
```

- [ ] **Step 2: Run test to verify it fails**

```
python test_tts_playback.py TestTtsBlocksMic
```

Expected: `AttributeError: 'SpeechWorker' object has no attribute 'tts_blocks_mic'`

- [ ] **Step 3: Write minimal implementation**

En `SpeechWorker.__init__`, junto a `_hug_tts_held`:

```python
        self._hug_tts_held = False
        self._tts_playback_end: float | None = None
        self._tts_is_story = False
```

Después de `is_busy`:

```python
    def tts_remaining_seconds(self) -> float | None:
        from session_policy import tts_remaining_seconds as remaining_fn

        speaking = (
            not self._idle_event.is_set()
            or self._pipeline_active
            or self._is_playing_music
        )
        return remaining_fn(
            time.monotonic(), self._tts_playback_end, speaking=speaking
        )

    def tts_blocks_mic(self) -> bool:
        from session_policy import tts_blocks_mic as blocks_fn

        return blocks_fn(
            self.tts_remaining_seconds(),
            is_music=self._is_playing_music,
            is_story=self._tts_is_story or self._pipeline_active,
        )
```

En `interrupt_playback`, después de `_idle_event.set()`:

```python
        self._tts_playback_end = time.monotonic()
        self._tts_is_story = False
```

En `speak_and_wait`, inmediatamente antes de `self._idle_event.clear()` (después de los returns tempranos):

```python
        self._tts_is_story = bool(story)
```

En `speak_sentences_and_wait`, inmediatamente antes de `self._idle_event.clear()` del camino multi-oración:

```python
        self._tts_is_story = True
```

En `_play_wav_via_output_stream`, **dentro** del `try` que abre `sd.OutputStream` con éxito, **antes** de `finished.wait`:

```python
                    n_frames = int(play_audio.shape[0])
                    dur = (n_frames / float(play_sr)) if play_sr else 0.0
                    self._tts_playback_end = time.monotonic() + dur
```

En el mismo `try`, en un `finally` de ese intento exitoso no hace falta si el `with` termina y `_run` pone idle. Añadir al salir de `_play_wav_via_output_stream` (al final de la función, y en cada `return` tras un play exitoso — hoy `return` está justo después del `with`):

```python
                    try:
                        with sd.OutputStream(...) as _stream:
                            finished.wait(timeout=len(play_audio) / play_sr + 5.0)
                    finally:
                        self._tts_playback_end = time.monotonic()
                    return
```

No cambiar el cuerpo del callback ni `is_busy()`.

- [ ] **Step 4: Run test to verify it passes**

```
python test_tts_playback.py TestTtsBlocksMic
python test_tts_playback.py
```

Expected: ambos `OK`.

---

### Task 3: AudioWorker half-duplex + cola viva

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`AudioWorker.__init__` ~1439; loop de captura ~1944 y ~2022; `_handle_segment` finally ~3138; `_speak_rps_response` ~2294; TTS principal ~3084; “No te escuché” ~2626; playtime ~3029)
- Test: `ProyectoParaRasperrypiV5/test_mic_input.py`

**Interfaces:**
- Consumes: `SpeechWorker.tts_blocks_mic()`, `keep_audio_queue_after_tts`
- Produces:
  - `AudioWorker._capture_muted: bool`
  - `AudioWorker._kept_tts_mic_tail: bool`
  - `AudioWorker._speaker_blocks_mic(self) -> bool`
  - `AudioWorker._set_capture_muted(self, muted: bool) -> None`
  - `AudioWorker._speak_conversational_keep_mic(self, text: str, audio_queue, timeout: float = 60.0) -> None`

- [ ] **Step 1: Write the failing tests**

En `test_mic_input.py`, agregar clase:

```python
class TestConversationalTtsKeepsMic(unittest.TestCase):
    def test_speaker_busy_usa_tts_blocks_mic(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        run_at = src.find("def _run(self)")
        audio_run = src[run_at : src.find("def _drain_audio_queue")]
        self.assertIn("tts_blocks_mic", audio_run)
        self.assertIn("_speaker_blocks_mic", audio_run)

    def test_handle_no_drena_si_keep_queue(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        start = src.find("def _handle_segment")
        end = src.find("def _truncate_response")
        chunk = src[start:end]
        self.assertIn("keep_audio_queue_after_tts", chunk)
        self.assertIn("_kept_tts_mic_tail", chunk)
        self.assertIn("_speak_conversational_keep_mic", chunk)

    def test_musica_sigue_silence_mic(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn("self._silence_mic_after_speaker(audio_queue)", src)
        play_at = src.find("music_to_play = intent_payload.get(\"play_music_file\")")
        self.assertGreater(play_at, 0)
        window = src[play_at : play_at + 500]
        self.assertIn("_silence_mic_after_speaker", window)
```

- [ ] **Step 2: Run test to verify it fails**

```
python test_mic_input.py TestConversationalTtsKeepsMic
```

Expected: FAIL (`tts_blocks_mic` / `_speak_conversational_keep_mic` no están en el chunk).

- [ ] **Step 3: Write minimal implementation**

En `AudioWorker.__init__` junto a `_echo_mute_until`:

```python
        self._echo_mute_until = 0.0
        self._capture_muted = True
        self._kept_tts_mic_tail = False
```

Métodos nuevos junto a `_silence_mic_after_speaker`:

```python
    def _speaker_blocks_mic(self) -> bool:
        if self._story_pipeline_active:
            return True
        sw = self.speech_worker
        if sw is None:
            return False
        return bool(sw.tts_blocks_mic())

    def _set_capture_muted(self, muted: bool) -> None:
        self._capture_muted = bool(muted)
        cap = self._alsa_capture
        if cap is not None:
            cap.set_muted(bool(muted))

    def _speak_conversational_keep_mic(
        self, text: str, audio_queue: queue.Queue, timeout: float = 60.0
    ) -> None:
        from session_policy import keep_audio_queue_after_tts

        if self.speech_worker is None or not str(text).strip():
            return
        self._set_capture_muted(False)
        self.speech_worker.speak_and_wait(text, timeout=timeout, story=False)
        if keep_audio_queue_after_tts(is_music=False, is_story=False):
            self._echo_mute_until = 0.0
            self._kept_tts_mic_tail = True
        else:
            self._silence_mic_after_speaker(audio_queue)
```

Reemplazar `_speaker_busy` interno del `_run` y el `speaker_on` de `listen_until_cut` para que llamen `self._speaker_blocks_mic()` (no `is_busy()`).

Callback Windows: `if self._capture_muted or _speaker_busy() or time.monotonic() < echo_until[0]:` — `_speaker_busy` ya apunta a `_speaker_blocks_mic`.

Donde hoy hace `capture.set_muted(True/False)` / `capture_muted[0] = ...`, usar `_set_capture_muted`. Quitar el listín local `capture_muted = [False]`.

Sustituir TTS conversacional:

- `_speak_rps_response`: `self._speak_conversational_keep_mic(response_text, audio_queue)` en lugar de `speak_and_wait` + `_silence_mic_after_speaker`.
- “No te escuché bien…”: igual.
- `PLAYTIME_DECLINE_PHRASE`: igual.
- En el bloque 12 de `_handle_segment`: si `story_chunk` / reflexión / `story_reflect_answer` → `_speak_story_payload` + `_silence_mic_after_speaker` (igual que hoy). `elif response_text` con `story_turn` True → `speak_and_wait(..., story=True)` + `_silence_mic_after_speaker`. `elif response_text` conversacional → `_speak_conversational_keep_mic`.

Música y `GO_TO_SLEEP`: siguen `_silence_mic_after_speaker`.

`finally` de `_handle_segment`:

```python
        finally:
            self._stt_in_flight = False
            if not self._kept_tts_mic_tail:
                while True:
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        break
            self._kept_tts_mic_tail = False
```

- [ ] **Step 4: Run test to verify it passes**

```
python test_mic_input.py TestConversationalTtsKeepsMic
python test_mic_input.py
python test_session_policy.py
python test_tts_playback.py
python test_alsa_capture.py
```

Expected: todos `OK`.

---

### Task 4: Subir a la Pi

**Files:** los de producción ya tocados (`session_policy.py`, `workers.py`; tests opcionales).

- [ ] **Step 1: SFTP**

```powershell
$env:PI_HOST = '192.168.0.148'
$env:PI_USER = 'teo'
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put session_policy.py workers.py test_session_policy.py test_tts_playback.py test_mic_input.py
```

Expected: una línea `ok <archivo> <bytes>` por cada put.

- [ ] **Step 2: Avisar a Teo**

Decir que hay que **reiniciar** `app.py`. No arrancarlo.

Verificación en dispositivo: frase de TEO + el chico habla en el último medio segundo; el log debe cortar `energy-vad: escuchando` sin esperar 0,4 s extra; no debe verse la cámara más oscura (este cambio no toca V4L2).

---

## Spec coverage

| Spec | Task |
|---|---|
| Abrir mic si remaining ≤ 0.50 en TTS conversacional | 1 + 2 |
| Remaining None (síntesis) bloquea | 1 + 2 |
| Frase &lt; 0.50 s abre al empezar playback | 1 (`0.50` inclusive) + 2 (`playback_end` al abrir stream) |
| `is_busy()` intacto | 2 |
| Música / cuento bloquean el tail | 1 + 2 + 3 |
| No drain + echo 0 tras TTS conversacional | 1 `keep_audio_queue_after_tts` + 3 |
| Drain + echo 0.40 música/cuento | 3 |
| Mute Whisper/LLM | 3 (`_set_capture_muted(True)` sigue antes de `_handle_segment`) |
| Interrupt invalida playback_end | 2 |
| Tests puros | 1, 2, 3 |
| SFTP, no autostart | 4 |
