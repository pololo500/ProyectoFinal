# Captura persistente arecord (ALSA hw 48 kHz) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (esta sesión) o superpowers:subagent-driven-development (un subagente fresco por tarea + review). TDD. Sin `git commit` salvo pedido de Teo.

**Goal:** En Linux (Raspberry Pi 5) reemplazar el `InputStream` de PortAudio por un `arecord` persistente a 48 kHz S16_LE mono sobre `hw:CARD=…,DEV=0`; el hilo drain nunca deja de leer; mute en TTS = no encolar al VAD; downsample 48→16 boxcar/3 fuera del hilo de lectura. Windows sigue en sounddevice a 16 kHz.

**Architecture:** Módulo nuevo `alsa_capture.py` (device string, Popen, drain, cola int16, mute, restart, stderr). `AudioWorker._run` abre la captura **una vez** después de Whisper/LLM y la mantiene hasta `stop`. Linux usa `AlsaCapture`; Windows mantiene `sd.InputStream` persistente a 16 kHz. `listen_until_cut` lee la misma cola; al cortar el segmento se drena la cola VAD (no se mata arecord), mute durante `_handle_segment`, unmute después de la ventana de eco. Playback no se toca (`SpeechWorker` `OutputStream`).

**Tech Stack:** Python 3.11, unittest (`python -m unittest …` desde `ProyectoParaRasperrypiV5`), `arecord` (alsa-utils) en la Pi, `sounddevice` solo Windows (captura) + playback ambos OS, `numpy`.

## Global Constraints

- Investigación aprobada (critic). **No copiar Wyoming 16 kHz ni `read(2048)`.**
- arecord persistente: `-D hw:CARD=…,DEV=0 -t raw -f S16_LE -c 1 -r 48000`. **No WAV, no plughw, no `-r 16000`, no `hw:1,0` como default guardado.**
- Pedido inicial ALSA: `--period-time=20000 --buffer-time=500000`, después loguear params negociados (stderr `-v` o parseo).
- Drain thread **nunca se detiene** (TTS/Whisper/LLM). Mute = no encolar. Dejar de leer ⇒ SIGPIPE / underrun del pipe.
- Windows: sounddevice **16 kHz** (`pi_mic_capture_rate()` ya devuelve 16000 en win32).
- Downsample **fuera** del hilo de lectura; N samples múltiplo de 3. Preferir `read(1920)` bytes = 960 frames @48 kHz = 20 ms.
- VAD: **no** dejar `silence_seconds += 0.128` hardcodeado. `silence_seconds +=` duración real del bloque post-STT. Recalcular pre-roll (~1 s) y buffer circular (~6 s) con el hop real.
- REESCRIBIR `test_cierra_el_mic_antes_de_whisper_y_llm`: el diseño nuevo **mantiene** la captura viva. El drain **sigue sin loguear**.
- Watchdog: read vacío + `poll()` → restart arecord. Drenar stderr (overrun/busy). **No** `--fatal-errors` en v1. **No** `-q` (esconde overrun). Preferir hilo stderr.
- PipeWire: si `hw:` está busy, **documentar** mask; no asumir sin `lsof`. No ejecutar mask desde la app en v1.
- `pipesize` 1 MiB si Python/kernel lo permiten; fallback 64 KiB.
- **No sudo.** El usuario `teo` está en el grupo `audio`.
- Seguir: `EmotionReactor.NORMAL_SILENCE = 1.2`, `AudioWorker.MAX_LISTEN_SECONDS = 15.0`, VAD energía en aarch64.
- `AUDIO_QUEUE_MAXSIZE = 128`. `enqueue_mic_block` / `apply_capture_drops` se reusan (Windows float32; Linux int16 en la cola cruda).
- `ECHO_MUTE_SECONDS = 0.40` (no cambiar el valor).
- Playback: `sounddevice` `OutputStream` (otra tarjeta). No mezclar captura y playback en el mismo PCM.
- Env override: `ALSA_CAPTURE_DEVICE` p.ej. `hw:CARD=Device,DEV=0`.
- TDD: test rojo **antes** de producción. unittest, **no pytest**.
- Sin commit salvo pedido de Teo (omitir todos los `git commit`).
- Tras **cada** cambio de producción: subir con `sftp_to_pi.py`. `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. **NUNCA** arrancar `app.py` salvo que Teo lo pida.
- Upload (PowerShell, cwd del archivo local; **no** `&&`; clave solo en env de la invocación):

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put alsa_capture.py
```

Esperado: `ok alsa_capture.py <bytes>`.
- Tests (cwd `ProyectoParaRasperrypiV5`):

```bash
python -m unittest test_alsa_capture test_mic_input
```

- **Prohibido como “fix”:** `dwc_otg`, `PA_ALSA_PLUGHW`, forzar 16 kHz sobre `hw:`, `plughw`, Wyoming 16 kHz, `read(2048)`.
- **No v1** (tareas posteriores, no implementar ahora): soxr, `nice -10`, pyalsaaudio, reglas udev, `--fatal-errors`.
- Plataforma: Windows 10/11 (PoC) + Raspberry Pi 5 8 GB, CPU only. El módulo `alsa_capture` se testea con fakes en Windows (no requiere `arecord` instalado).
- El callback/drain **no** importa `session_policy` en cada bloque. `mic_open_for_listen` queda en `listen_until_cut` (hilo VAD).
- No cambiar loopback de `app.py` (`sd.rec` de la UI).

## Files

- Create: `ProyectoParaRasperrypiV5/alsa_capture.py`
- Create: `ProyectoParaRasperrypiV5/test_alsa_capture.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`pi_mic_capture_rate` se queda; helpers de hop; `AudioWorker.__init__`/`stop`/`_run`; callback Windows)
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py` (`TestPiMicFijo`, `TestMicHalfDuplex`, `TestEndpointingYCola`)
- Modify: `ProyectoParaRasperrypiV5/Agents.md` (captura Linux = arecord)
- Modify: `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md` (sección 2026-09-08 arecord; PipeWire; grupo audio)

No modificar: `SpeechWorker._play_wav_via_output_stream`, `session_policy.ECHO_MUTE_SECONDS`, `EmotionReactor.NORMAL_SILENCE`, `whisper_process.py`.

---

### Task 1: Device string ALSA (`hw:CARD=…,DEV=0`)

**Files:**
- Create: `ProyectoParaRasperrypiV5/test_alsa_capture.py`
- Create: `ProyectoParaRasperrypiV5/alsa_capture.py`

**Interfaces:**
- Consumes: texto de `arecord -l`; nombre sounddevice; `os.environ["ALSA_CAPTURE_DEVICE"]`.
- Produces:
  - `ENV_ALSA_CAPTURE_DEVICE = "ALSA_CAPTURE_DEVICE"`
  - `class AlsaCard` con `card_id: str`, `card_index: int`, `long_name: str`, `device: int`
  - `parse_arecord_cards(arecord_l: str) -> list[AlsaCard]`
  - `hw_device_string(card: AlsaCard) -> str` → `hw:CARD={card_id},DEV={device}`
  - `match_card_for_sounddevice_name(sd_name: str, cards: list[AlsaCard]) -> AlsaCard | None`
  - `resolve_alsa_capture_device(*, env: Mapping[str, str] | None, arecord_l: str, sounddevice_name: str) -> str`
  - `arecord_list_argv() -> list[str]` → `["arecord", "-l"]`
  - `read_arecord_list() -> str` (subprocess de ese argv; tests no lo llaman)

- [ ] **Step 1: Write the failing tests**

Crear `ProyectoParaRasperrypiV5/test_alsa_capture.py`:

```python
"""Captura ALSA persistente: device string, arecord argv, drain, watchdog."""
from __future__ import annotations

import os
import queue
import unittest
from unittest.mock import patch

import numpy as np

from alsa_capture import (
    ENV_ALSA_CAPTURE_DEVICE,
    AlsaCard,
    arecord_list_argv,
    hw_device_string,
    match_card_for_sounddevice_name,
    parse_arecord_cards,
    resolve_alsa_capture_device,
)

FAKE_ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""

SD_USB = "USB PnP Sound Device: USB Audio (hw:2,0)"


class TestArecordDeviceString(unittest.TestCase):
    def test_parsea_card_id_no_el_indice_numeric(self) -> None:
        cards = parse_arecord_cards(FAKE_ARECORD_L)
        usb = [c for c in cards if c.card_id == "Device"]
        self.assertEqual(len(usb), 1)
        self.assertEqual(usb[0].card_index, 2)
        self.assertEqual(usb[0].long_name, "USB PnP Sound Device")
        self.assertEqual(usb[0].device, 0)

    def test_hw_string_usa_CARD_no_hw_1_0(self) -> None:
        card = AlsaCard(card_id="Device", card_index=2, long_name="USB PnP Sound Device", device=0)
        self.assertEqual(hw_device_string(card), "hw:CARD=Device,DEV=0")
        self.assertNotEqual(hw_device_string(card), "hw:1,0")
        self.assertNotEqual(hw_device_string(card), "hw:2,0")

    def test_match_por_nombre_usb_aunque_sd_diga_hw_2_0(self) -> None:
        cards = parse_arecord_cards(FAKE_ARECORD_L)
        matched = match_card_for_sounddevice_name(SD_USB, cards)
        self.assertIsNotNone(matched)
        self.assertEqual(hw_device_string(matched), "hw:CARD=Device,DEV=0")

    def test_no_elige_hdmi_si_el_nombre_es_usb(self) -> None:
        cards = parse_arecord_cards(FAKE_ARECORD_L)
        matched = match_card_for_sounddevice_name(SD_USB, cards)
        self.assertEqual(matched.card_id, "Device")
        self.assertNotEqual(matched.card_id, "vc4hdmi0")

    def test_env_override_gana(self) -> None:
        device = resolve_alsa_capture_device(
            env={ENV_ALSA_CAPTURE_DEVICE: "hw:CARD=Device,DEV=0"},
            arecord_l=FAKE_ARECORD_L,
            sounddevice_name="algo que no matchea",
        )
        self.assertEqual(device, "hw:CARD=Device,DEV=0")

    def test_sin_env_resuelve_por_arecord_l(self) -> None:
        device = resolve_alsa_capture_device(
            env={},
            arecord_l=FAKE_ARECORD_L,
            sounddevice_name=SD_USB,
        )
        self.assertEqual(device, "hw:CARD=Device,DEV=0")

    def test_sin_match_no_cae_a_hw_1_0(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_alsa_capture_device(
                env={},
                arecord_l=FAKE_ARECORD_L,
                sounddevice_name="Microfono inventado XYZ",
            )
        self.assertNotIn("hw:1,0", str(ctx.exception))

    def test_list_argv_es_arecord_l_sin_sudo(self) -> None:
        argv = arecord_list_argv()
        self.assertEqual(argv, ["arecord", "-l"])
        self.assertNotIn("sudo", argv)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `ProyectoParaRasperrypiV5`):

```bash
python -m unittest test_alsa_capture.TestArecordDeviceString -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'alsa_capture'` (o ImportError de los nombres).

- [ ] **Step 3: Write minimal implementation**

Crear `ProyectoParaRasperrypiV5/alsa_capture.py`:

```python
"""Captura persistente via arecord (ALSA hw:, 48 kHz S16_LE mono). Solo Linux en producción."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

ENV_ALSA_CAPTURE_DEVICE = "ALSA_CAPTURE_DEVICE"

_CARD_RE = re.compile(
    r"card\s+(?P<index>\d+):\s+(?P<id>\S+)\s+\[(?P<long>[^\]]+)\],\s+"
    r"device\s+(?P<dev>\d+):",
    re.MULTILINE,
)


@dataclass(frozen=True)
class AlsaCard:
    card_id: str
    card_index: int
    long_name: str
    device: int


def arecord_list_argv() -> list[str]:
    return ["arecord", "-l"]


def parse_arecord_cards(arecord_l: str) -> list[AlsaCard]:
    cards: list[AlsaCard] = []
    for match in _CARD_RE.finditer(arecord_l or ""):
        cards.append(
            AlsaCard(
                card_id=match.group("id"),
                card_index=int(match.group("index")),
                long_name=match.group("long"),
                device=int(match.group("dev")),
            )
        )
    return cards


def hw_device_string(card: AlsaCard) -> str:
    return f"hw:CARD={card.card_id},DEV={card.device}"


def match_card_for_sounddevice_name(
    sd_name: str,
    cards: list[AlsaCard],
) -> AlsaCard | None:
    name = (sd_name or "").lower()
    if not name or not cards:
        return None
    for card in cards:
        if card.long_name.lower() in name or card.card_id.lower() in name:
            return card
    return None


def resolve_alsa_capture_device(
    *,
    env: Mapping[str, str] | None,
    arecord_l: str,
    sounddevice_name: str,
) -> str:
    environ = env if env is not None else os.environ
    override = str(environ.get(ENV_ALSA_CAPTURE_DEVICE, "") or "").strip()
    if override:
        return override
    cards = parse_arecord_cards(arecord_l)
    matched = match_card_for_sounddevice_name(sounddevice_name, cards)
    if matched is None:
        raise ValueError(
            "No hay tarjeta ALSA de captura que coincida con "
            f"{sounddevice_name!r}. arecord -l:\n{arecord_l}"
        )
    return hw_device_string(matched)


def read_arecord_list() -> str:
    result = subprocess.run(
        arecord_list_argv(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_alsa_capture.TestArecordDeviceString -v
```

Expected: PASS (8 tests).

- [ ] **Step 5: Upload producción**

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put ProyectoParaRasperrypiV5/alsa_capture.py ProyectoParaRasperrypiV5/test_alsa_capture.py
```

Expected: `ok alsa_capture.py …` y `ok test_alsa_capture.py …`. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir. Teo no pidió commit.

---

### Task 2: argv de arecord (48 kHz raw, 20 ms, period/buffer)

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_alsa_capture.py`
- Modify: `ProyectoParaRasperrypiV5/alsa_capture.py`

**Interfaces:**
- Consumes: `device: str` de Task 1.
- Produces:
  - `ALSA_RATE = 48000`
  - `ALSA_CHANNELS = 1`
  - `ALSA_FORMAT = "S16_LE"`
  - `ALSA_FRAMES_PER_READ = 960`
  - `ALSA_READ_BYTES = 1920`
  - `ALSA_PERIOD_TIME_US = 20000`
  - `ALSA_BUFFER_TIME_US = 500000`
  - `build_arecord_argv(device: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Añadir al final de `test_alsa_capture.py` (antes de `if __name__`):

```python
from alsa_capture import (
    ALSA_BUFFER_TIME_US,
    ALSA_FRAMES_PER_READ,
    ALSA_PERIOD_TIME_US,
    ALSA_RATE,
    ALSA_READ_BYTES,
    build_arecord_argv,
)


class TestArecordArgv(unittest.TestCase):
    def test_read_es_1920_bytes_20ms(self) -> None:
        self.assertEqual(ALSA_RATE, 48000)
        self.assertEqual(ALSA_FRAMES_PER_READ, 960)
        self.assertEqual(ALSA_READ_BYTES, 1920)
        self.assertEqual(ALSA_FRAMES_PER_READ * 2, ALSA_READ_BYTES)
        self.assertAlmostEqual(ALSA_FRAMES_PER_READ / ALSA_RATE, 0.020)

    def test_argv_hw_raw_s16_48k_mono(self) -> None:
        argv = build_arecord_argv("hw:CARD=Device,DEV=0")
        self.assertEqual(argv[0], "arecord")
        self.assertNotIn("sudo", argv)
        joined = " ".join(argv)
        self.assertIn("-D", argv)
        self.assertIn("hw:CARD=Device,DEV=0", argv)
        self.assertIn("-t", argv)
        self.assertIn("raw", argv)
        self.assertIn("-f", argv)
        self.assertIn("S16_LE", argv)
        self.assertIn("-c", argv)
        self.assertIn("1", argv)
        self.assertIn("-r", argv)
        self.assertIn("48000", argv)
        self.assertIn(f"--period-time={ALSA_PERIOD_TIME_US}", argv)
        self.assertIn(f"--buffer-time={ALSA_BUFFER_TIME_US}", argv)
        self.assertIn("-v", argv)
        self.assertNotIn("-q", argv)
        self.assertNotIn("--fatal-errors", argv)
        self.assertNotIn("plughw", joined)
        self.assertNotIn("wav", joined.lower())
        self.assertNotIn("16000", argv)
        self.assertNotIn("hw:1,0", argv)
        self.assertNotIn("2048", argv)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_alsa_capture.TestArecordArgv -v
```

Expected: FAIL (`ImportError` de `build_arecord_argv` / constantes).

- [ ] **Step 3: Write minimal implementation**

En `alsa_capture.py`, junto a las constantes de Task 1:

```python
ALSA_RATE = 48000
ALSA_CHANNELS = 1
ALSA_FORMAT = "S16_LE"
ALSA_FRAMES_PER_READ = 960
ALSA_READ_BYTES = ALSA_FRAMES_PER_READ * 2  # S16_LE mono
ALSA_PERIOD_TIME_US = 20000
ALSA_BUFFER_TIME_US = 500000


def build_arecord_argv(device: str) -> list[str]:
    return [
        "arecord",
        "-D",
        device,
        "-t",
        "raw",
        "-f",
        ALSA_FORMAT,
        "-c",
        str(ALSA_CHANNELS),
        "-r",
        str(ALSA_RATE),
        f"--period-time={ALSA_PERIOD_TIME_US}",
        f"--buffer-time={ALSA_BUFFER_TIME_US}",
        "-v",
    ]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_alsa_capture.TestArecordArgv test_alsa_capture.TestArecordDeviceString -v
```

Expected: PASS.

- [ ] **Step 5: Upload producción**

Mismo `sftp_to_pi.py --put` de `alsa_capture.py` y `test_alsa_capture.py` con `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir.

---

### Task 3: Drain — leer siempre, mute = no encolar, sin downsample ni logs

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_alsa_capture.py`
- Modify: `ProyectoParaRasperrypiV5/alsa_capture.py`
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py` (el downsample sigue fuera: ampliar `test_audio_worker_no_reesamplea_en_el_callback`)

**Interfaces:**
- Consumes: `enqueue_mic_block(audio_queue, block, drop_hits)` de `workers.py` (inyectada; **no** importar `workers` desde `alsa_capture` a nivel módulo — ciclo).
- Produces:
  - `consume_raw_pcm(raw: bytes, muted: bool, audio_queue, drop_hits: list[int], enqueue: Callable, leftover: bytes = b"") -> bytes`
  - `pcm_s16le_bytes_to_int16(block: bytes) -> np.ndarray` (dtype int16, size 960)
  - `class AlsaCapture` con `set_muted(muted: bool) -> None`, `_muted: bool`, `overrun_hits: int`, `busy_hits: int`, `restarts: int`, `negotiated: dict[str, int]`, `pipe_size: int`
  - Drain **no** llama `downsample_capture_to_stt`. **no** importa `session_policy`. **no** llama `log_action` ni `_queue_message`.

- [ ] **Step 1: Write the failing tests**

En `test_alsa_capture.py` añadir imports y clase:

```python
from pathlib import Path

import threading
import time

from alsa_capture import AlsaCapture, consume_raw_pcm, pcm_s16le_bytes_to_int16
from workers import enqueue_mic_block


class TestDrainConsume(unittest.TestCase):
    def test_unmute_encola_int16_960_sin_downsample(self) -> None:
        frames = np.arange(960, dtype=np.int16)
        q: queue.Queue = queue.Queue()
        drops = [0]
        leftover = consume_raw_pcm(
            frames.tobytes(),
            False,
            q,
            drops,
            enqueue_mic_block,
        )
        self.assertEqual(leftover, b"")
        block = q.get_nowait()
        self.assertEqual(block.dtype, np.int16)
        self.assertEqual(block.size, 960)
        np.testing.assert_array_equal(block, frames)

    def test_mute_no_encola_pero_consume_bytes(self) -> None:
        frames = np.ones(960, dtype=np.int16)
        q: queue.Queue = queue.Queue()
        drops = [0]
        leftover = consume_raw_pcm(
            frames.tobytes(),
            True,
            q,
            drops,
            enqueue_mic_block,
        )
        self.assertTrue(q.empty())
        self.assertEqual(leftover, b"")
        self.assertEqual(drops[0], 0)

    def test_parcial_queda_en_leftover(self) -> None:
        q: queue.Queue = queue.Queue()
        drops = [0]
        leftover = consume_raw_pcm(
            b"\x00\x01\x02",
            False,
            q,
            drops,
            enqueue_mic_block,
        )
        self.assertTrue(q.empty())
        self.assertEqual(leftover, b"\x00\x01\x02")

    def test_pcm_s16le_little_endian(self) -> None:
        raw = np.array([-1, 0, 1], dtype=np.int16).tobytes()
        out = pcm_s16le_bytes_to_int16(raw)
        self.assertEqual(out.dtype, np.int16)
        np.testing.assert_array_equal(out, np.array([-1, 0, 1], dtype=np.int16))

    def test_modulo_no_importa_session_policy_ni_loguea(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("alsa_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("session_policy", src)
        self.assertNotIn("log_action", src)
        self.assertNotIn("_queue_message", src)
        self.assertNotIn("downsample_capture_to_stt", src)
        self.assertNotIn("print(", src)


class TestAlsaMuteGate(unittest.TestCase):
    def _cap(self, busy: bool = False) -> AlsaCapture:
        return AlsaCapture(
            device="hw:CARD=Device,DEV=0",
            audio_queue=queue.Queue(),
            drop_hits=[0],
            stop_event=threading.Event(),
            enqueue=enqueue_mic_block,
            speaker_busy=lambda: busy,
            echo_until=[0.0],
        )

    def test_muted_no_encola(self) -> None:
        cap = self._cap()
        cap.set_muted(True)
        self.assertFalse(cap._should_enqueue())

    def test_echo_futuro_no_encola(self) -> None:
        cap = self._cap()
        cap._echo_until[0] = time.monotonic() + 10.0
        self.assertFalse(cap._should_enqueue())

    def test_speaker_busy_no_encola(self) -> None:
        cap = self._cap(busy=True)
        self.assertFalse(cap._should_enqueue())

    def test_libre_encola(self) -> None:
        cap = self._cap()
        cap.set_muted(False)
        self.assertTrue(cap._should_enqueue())
```

En `test_mic_input.py`, ampliar `test_audio_worker_no_reesamplea_en_el_callback`:

```python
    def test_audio_worker_no_reesamplea_en_el_callback(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mic_block_to_stt(indata", src)
        self.assertIn("pi_mic_capture_rate()", src)
        self.assertIn("downsample_capture_to_stt(", src)
        alsa = Path(__file__).resolve().parent.joinpath("alsa_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("downsample_capture_to_stt", alsa)
        self.assertNotIn("SpeechWorker._resample_audio", alsa)
```

(El assert de `alsa_capture.py` fallará hasta que el archivo exista con esas garantías; tras Task 1 ya existe y no tiene downsample → este assert pasa. El de `consume_raw_pcm` es el rojo de esta tarea.)

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_alsa_capture.TestDrainConsume test_alsa_capture.TestAlsaMuteGate -v
```

Expected: FAIL (`cannot import name consume_raw_pcm` y/o `AlsaCapture`).

- [ ] **Step 3: Write minimal implementation**

En `alsa_capture.py`:

```python
# Ampliar el import de Task 1: from typing import Any, Callable, Mapping
from typing import Any


def pcm_s16le_bytes_to_int16(block: bytes) -> np.ndarray:
    return np.frombuffer(block, dtype="<i2").copy()


def consume_raw_pcm(
    raw: bytes,
    muted: bool,
    audio_queue: Any,
    drop_hits: list[int],
    enqueue: Callable[..., None],
    leftover: bytes = b"",
) -> bytes:
    buf = leftover + raw
    view = memoryview(buf)
    offset = 0
    while len(view) - offset >= ALSA_READ_BYTES:
        piece = bytes(view[offset : offset + ALSA_READ_BYTES])
        offset += ALSA_READ_BYTES
        if muted:
            continue
        enqueue(audio_queue, pcm_s16le_bytes_to_int16(piece), drop_hits)
    return bytes(view[offset:])
```

Añadir la clase `AlsaCapture` (mute + gate). `start`/`stop`/drain se completan en Task 4; acá alcanzan `__init__`, `set_muted` y `_should_enqueue` para que `TestAlsaMuteGate` pase.

```python
class AlsaCapture:
    def __init__(
        self,
        device: str,
        audio_queue: Any,
        drop_hits: list[int],
        stop_event: threading.Event,
        enqueue: Callable[..., None],
        speaker_busy: Callable[[], bool] | None = None,
        echo_until: list[float] | None = None,
    ) -> None:
        self.device = device
        self.audio_queue = audio_queue
        self.drop_hits = drop_hits
        self._stop_event = stop_event
        self._enqueue = enqueue
        self._speaker_busy = speaker_busy
        self._echo_until = echo_until if echo_until is not None else [0.0]
        self._muted = False
        self._proc: subprocess.Popen | None = None
        self._leftover = b""
        self.overrun_hits = 0
        self.busy_hits = 0
        self.restarts = 0
        self.negotiated: dict[str, int] = {}
        self.pipe_size = 0
        self._drain_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def _should_enqueue(self) -> bool:
        if self._muted:
            return False
        if time.monotonic() < float(self._echo_until[0]):
            return False
        if self._speaker_busy is not None and self._speaker_busy():
            return False
        return True
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_alsa_capture.TestDrainConsume test_alsa_capture.TestAlsaMuteGate test_mic_input.TestPiMicFijo.test_audio_worker_no_reesamplea_en_el_callback -v
```

Expected: PASS.

- [ ] **Step 5: Upload producción**

`--put alsa_capture.py test_alsa_capture.py test_mic_input.py` con `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir.

---

### Task 4: Watchdog, stderr (overrun/busy), pipesize

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_alsa_capture.py`
- Modify: `ProyectoParaRasperrypiV5/alsa_capture.py`

**Interfaces:**
- Consumes: `build_arecord_argv`, `consume_raw_pcm`, `ALSA_READ_BYTES`.
- Produces:
  - `PIPE_SIZE_PREFERRED = 1024 * 1024`
  - `PIPE_SIZE_FALLBACK = 64 * 1024`
  - `apply_pipe_size(fd: int) -> int`
  - `should_restart_arecord(*, n_read: int, poll_rc: int | None, stopping: bool) -> bool`
  - `note_arecord_stderr_line(line: str, stats: dict[str, int]) -> None` (mutates `overrun`, `busy`, `period_time`, `buffer_time`)
  - `AlsaCapture.start() / stop() / _spawn() / _restart() / _drain_loop() / _stderr_loop()`
  - `AlsaCapture._read_chunk(proc) -> bytes`

Reglas watchdog:
- `stopping=True` → no restart.
- `poll_rc is not None` → restart (proceso muerto).
- `n_read == 0` tras `read`/`os.read` (EOF) → restart.
- timeout de `select` **con proceso vivo** (`poll_rc is None` y no es EOF) → **no** restart (evita flapping). En código: `_read_chunk` distingue timeout (`None` sentinela) vs EOF (`b""`).
- `should_restart_arecord(n_read=0, poll_rc=None, stopping=False)` para EOF explícito sí restart cuando `_read_chunk` devolvió `b""`.

- [ ] **Step 1: Write the failing tests**

```python
from alsa_capture import (
    PIPE_SIZE_FALLBACK,
    PIPE_SIZE_PREFERRED,
    apply_pipe_size,
    note_arecord_stderr_line,
    should_restart_arecord,
)


class TestWatchdogYStderr(unittest.TestCase):
    def test_eof_reinicia(self) -> None:
        self.assertTrue(
            should_restart_arecord(n_read=0, poll_rc=None, stopping=False)
        )

    def test_poll_muerto_reinicia(self) -> None:
        self.assertTrue(
            should_restart_arecord(n_read=1920, poll_rc=1, stopping=False)
        )

    def test_stop_no_reinicia(self) -> None:
        self.assertFalse(
            should_restart_arecord(n_read=0, poll_rc=1, stopping=True)
        )

    def test_timeout_vivo_no_reinicia(self) -> None:
        # n_read=-1 = select timeout, proceso vivo
        self.assertFalse(
            should_restart_arecord(n_read=-1, poll_rc=None, stopping=False)
        )

    def test_datos_vivos_no_reinicia(self) -> None:
        self.assertFalse(
            should_restart_arecord(n_read=1920, poll_rc=None, stopping=False)
        )

    def test_stderr_overrun_y_busy(self) -> None:
        stats = {"overrun": 0, "busy": 0, "period_time": 0, "buffer_time": 0}
        note_arecord_stderr_line("overrun!!!", stats)
        note_arecord_stderr_line("arecord: Device or resource busy", stats)
        note_arecord_stderr_line("  period_time  : 20000", stats)
        note_arecord_stderr_line("  buffer_time  : 500000", stats)
        self.assertEqual(stats["overrun"], 1)
        self.assertEqual(stats["busy"], 1)
        self.assertEqual(stats["period_time"], 20000)
        self.assertEqual(stats["buffer_time"], 500000)

    def test_pipesize_cae_a_64k_si_1m_falla(self) -> None:
        calls: list[int] = []

        def fake_set(fd: int, size: int) -> int:
            calls.append(size)
            if size == PIPE_SIZE_PREFERRED:
                raise OSError("too big")
            return size

        with patch("alsa_capture.fcntl_set_pipe_size", side_effect=fake_set):
            applied = apply_pipe_size(3)
        self.assertEqual(applied, PIPE_SIZE_FALLBACK)
        self.assertEqual(calls, [PIPE_SIZE_PREFERRED, PIPE_SIZE_FALLBACK])

    def test_pipesize_1m_si_el_kernel_deja(self) -> None:
        with patch("alsa_capture.fcntl_set_pipe_size", return_value=PIPE_SIZE_PREFERRED):
            self.assertEqual(apply_pipe_size(3), PIPE_SIZE_PREFERRED)
```

`apply_pipe_size` debe llamar a `fcntl_set_pipe_size` (testeable en Windows). Implementación:

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_alsa_capture.TestWatchdogYStderr -v
```

Expected: FAIL (nombres no definidos).

- [ ] **Step 3: Write minimal implementation**

En `alsa_capture.py`:

```python
import select

PIPE_SIZE_PREFERRED = 1024 * 1024
PIPE_SIZE_FALLBACK = 64 * 1024


def fcntl_set_pipe_size(fd: int, size: int) -> int:
    import fcntl

    cmd = getattr(fcntl, "F_SETPIPE_SZ", 1031)
    fcntl.fcntl(fd, cmd, size)
    return size


def apply_pipe_size(fd: int) -> int:
    for size in (PIPE_SIZE_PREFERRED, PIPE_SIZE_FALLBACK):
        try:
            fcntl_set_pipe_size(fd, size)
            return size
        except OSError:
            continue
    return 0


def should_restart_arecord(
    *,
    n_read: int,
    poll_rc: int | None,
    stopping: bool,
) -> bool:
    if stopping:
        return False
    if poll_rc is not None:
        return True
    if n_read == 0:
        return True
    return False


def note_arecord_stderr_line(line: str, stats: dict[str, int]) -> None:
    low = (line or "").lower()
    if "overrun" in low:
        stats["overrun"] = int(stats.get("overrun", 0)) + 1
    if "busy" in low:
        stats["busy"] = int(stats.get("busy", 0)) + 1
    stripped = line.strip()
    if "period_time" in stripped:
        bits = stripped.split(":")
        if len(bits) >= 2:
            try:
                stats["period_time"] = int(bits[-1].strip().split()[0])
            except ValueError:
                pass
    if "buffer_time" in stripped:
        bits = stripped.split(":")
        if len(bits) >= 2:
            try:
                stats["buffer_time"] = int(bits[-1].strip().split()[0])
            except ValueError:
                pass
```

Completar `AlsaCapture` (mismos nombres que Task 3; no duplicar `__init__`):

```python
    def start(self) -> None:
        self._spawn()
        self._drain_thread = threading.Thread(
            target=self._drain_loop, name="AlsaDrain", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, name="AlsaStderr", daemon=True
        )
        self._drain_thread.start()
        self._stderr_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None

    def _spawn(self) -> None:
        proc = subprocess.Popen(
            build_arecord_argv(self.device),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._proc = proc
        if proc.stdout is not None:
            try:
                self.pipe_size = apply_pipe_size(proc.stdout.fileno())
            except Exception:
                self.pipe_size = 0

    def _restart(self) -> None:
        if self._stop_event.is_set():
            return
        old = self._proc
        if old is not None:
            try:
                old.kill()
            except Exception:
                pass
            try:
                old.wait(timeout=0.5)
            except Exception:
                pass
        self.restarts += 1
        self._leftover = b""
        time.sleep(0.2)
        self._spawn()
        if self._stderr_thread is None or not self._stderr_thread.is_alive():
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop, name="AlsaStderr", daemon=True
            )
            self._stderr_thread.start()

    def _read_chunk(self, proc: subprocess.Popen) -> bytes | None:
        """bytes = datos o EOF; None = select timeout (proceso vivo)."""
        stdout = proc.stdout
        if stdout is None:
            return b""
        try:
            ready, _, _ = select.select([stdout], [], [], 1.0)
        except (OSError, ValueError, TypeError):
            ready = [stdout]
        if not ready:
            return None
        try:
            return os.read(stdout.fileno(), ALSA_READ_BYTES)
        except Exception:
            return b""

    def _drain_loop(self) -> None:
        while not self._stop_event.is_set():
            proc = self._proc
            if proc is None:
                self._restart()
                continue
            chunk = self._read_chunk(proc)
            poll_rc = proc.poll()
            if chunk is None:
                if should_restart_arecord(
                    n_read=-1, poll_rc=poll_rc, stopping=self._stop_event.is_set()
                ):
                    self._restart()
                continue
            if should_restart_arecord(
                n_read=len(chunk),
                poll_rc=poll_rc,
                stopping=self._stop_event.is_set(),
            ):
                self._restart()
                continue
            muted = not self._should_enqueue()
            self._leftover = consume_raw_pcm(
                chunk,
                muted,
                self.audio_queue,
                self.drop_hits,
                self._enqueue,
                leftover=self._leftover,
            )

    def _stderr_loop(self) -> None:
        while not self._stop_event.is_set():
            proc = self._proc
            if proc is None or proc.stderr is None:
                time.sleep(0.05)
                continue
            line = proc.stderr.readline()
            if not line:
                time.sleep(0.05)
                continue
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
            stats = {
                "overrun": 0,
                "busy": 0,
                "period_time": int(self.negotiated.get("period_time", 0)),
                "buffer_time": int(self.negotiated.get("buffer_time", 0)),
            }
            note_arecord_stderr_line(text, stats)
            self.overrun_hits += int(stats["overrun"])
            self.busy_hits += int(stats["busy"])
            if stats.get("period_time"):
                self.negotiated["period_time"] = stats["period_time"]
            if stats.get("buffer_time"):
                self.negotiated["buffer_time"] = stats["buffer_time"]
```

El hilo drain **nunca sale** salvo `_stop_event`. `_restart` no hace `return` del loop. Stderr **solo** incrementa contadores / `negotiated`; cero logs.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_alsa_capture -v
```

Expected: PASS (todas las clases de este archivo).

- [ ] **Step 5: Upload producción**

`--put alsa_capture.py test_alsa_capture.py`. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir.

---

### Task 5: Timing VAD por duración real (20 ms Linux / 128 ms Windows)

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py`
- Modify: `ProyectoParaRasperrypiV5/workers.py` (helpers junto a `downsample_capture_to_stt`; `listen_until_cut` deja de sumar `0.128`)

**Interfaces:**
- Consumes: `ALSA_FRAMES_PER_READ` / `ALSA_RATE` (0.020 s); Windows hop 0.128 s; `STT_SAMPLE_RATE = 16000`.
- Produces:
  - `pcm_s16le_to_float32(block: np.ndarray) -> np.ndarray`
  - `stt_block_duration_seconds(n_samples: int, sample_rate: int = STT_SAMPLE_RATE) -> float`
  - `capture_hop_seconds(platform_name: str | None = None) -> float`
  - `vad_pre_roll_blocks(hop_seconds: float, pre_roll_seconds: float = 1.0) -> int`
  - `vad_circular_maxlen(hop_seconds: float, window_seconds: float = 6.0) -> int`
  - En `listen_until_cut`: convertir int16→float32, `downsample_capture_to_stt`, `silence_seconds += duration`, `listen_seconds += duration` con `duration = stt_block_duration_seconds(len(audio_block), stt_rate)`.

- [ ] **Step 1: Write the failing tests**

En `test_mic_input.py` imports:

```python
from workers import (
    capture_hop_seconds,
    pcm_s16le_to_float32,
    stt_block_duration_seconds,
    vad_circular_maxlen,
    vad_pre_roll_blocks,
)
```

Nueva clase:

```python
class TestVadHopReal(unittest.TestCase):
    def test_linux_hop_es_20ms(self) -> None:
        self.assertAlmostEqual(capture_hop_seconds("linux"), 0.020)

    def test_windows_hop_sigue_128ms(self) -> None:
        self.assertAlmostEqual(capture_hop_seconds("win32"), 0.128)

    def test_pre_roll_y_circular_con_20ms(self) -> None:
        self.assertEqual(vad_pre_roll_blocks(0.020), 50)
        self.assertEqual(vad_circular_maxlen(0.020), 300)

    def test_pre_roll_y_circular_con_128ms(self) -> None:
        self.assertEqual(vad_pre_roll_blocks(0.128), 8)
        self.assertEqual(vad_circular_maxlen(0.128), 47)

    def test_duracion_320_samples_16k(self) -> None:
        self.assertAlmostEqual(stt_block_duration_seconds(320, 16000), 0.020)

    def test_duracion_2048_samples_16k(self) -> None:
        self.assertAlmostEqual(stt_block_duration_seconds(2048, 16000), 0.128)

    def test_int16_a_float_simetrico(self) -> None:
        x = np.array([0, 32767, -32768], dtype=np.int16)
        out = pcm_s16le_to_float32(x)
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out[0]), 0.0, delta=1e-6)
        self.assertGreater(float(out[1]), 0.99)
        self.assertLess(float(out[2]), -0.99)

    def test_listen_suma_duracion_real_no_0128(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("silence_seconds += block_duration_seconds", src)
        self.assertIn("stt_block_duration_seconds(", src)
        self.assertIn("pcm_s16le_to_float32(", src)
```

El último test es el contrato de `listen_until_cut`: falla mientras `_run` siga con `silence_seconds += block_duration_seconds`.

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_mic_input.TestVadHopReal -v
```

Expected: FAIL (`cannot import name capture_hop_seconds` y/o el source assert de `+= block_duration_seconds`).

- [ ] **Step 3: Write minimal implementation**

En `workers.py`, debajo de `downsample_capture_to_stt`:

```python
def pcm_s16le_to_float32(block: np.ndarray) -> np.ndarray:
    arr = np.asarray(block).reshape(-1)
    if arr.dtype != np.int16:
        arr = arr.astype(np.int16, copy=False)
    return arr.astype(np.float32) * (1.0 / 32768.0)


def stt_block_duration_seconds(
    n_samples: int,
    sample_rate: int = STT_SAMPLE_RATE,
) -> float:
    if sample_rate <= 0 or n_samples <= 0:
        return 0.0
    return float(n_samples) / float(sample_rate)


def capture_hop_seconds(platform_name: str | None = None) -> float:
    name = sys.platform if platform_name is None else platform_name
    if str(name).startswith("linux"):
        return 960.0 / 48000.0
    return 0.128


def vad_pre_roll_blocks(hop_seconds: float, pre_roll_seconds: float = 1.0) -> int:
    hop = max(float(hop_seconds), 1e-6)
    return max(1, int(round(pre_roll_seconds / hop)))


def vad_circular_maxlen(hop_seconds: float, window_seconds: float = 6.0) -> int:
    hop = max(float(hop_seconds), 1e-6)
    return max(8, int(round(window_seconds / hop)))
```

En `AudioWorker._run`, reemplazar el bloque que hoy es:

```python
        capture_sr = pi_mic_capture_rate()
        block_duration_seconds = 0.128
        ...
        block_size = int(capture_sr * block_duration_seconds)
        ...
        circular_maxlen = max(8, int(round(6.0 / block_duration_seconds)))
        ...
        pre_roll_blocks = max(1, int(round(1.0 / block_duration_seconds)))
```

por:

```python
        capture_sr = pi_mic_capture_rate()
        hop_seconds = capture_hop_seconds()
        block_size = int(round(capture_sr * hop_seconds))
        silence_threshold_seconds = self.emotion_reactor.NORMAL_SILENCE
        max_listen_seconds = self.MAX_LISTEN_SECONDS
        circular_maxlen = vad_circular_maxlen(hop_seconds)
        circular_buffer: deque[np.ndarray] = deque(maxlen=circular_maxlen)
        pre_roll_blocks = vad_pre_roll_blocks(hop_seconds)
```

Dentro de `listen_until_cut`, **después** de `audio_queue.get`, **antes** de RMS/VAD:

```python
                    if np.issubdtype(audio_block.dtype, np.integer):
                        audio_block = pcm_s16le_to_float32(audio_block)
                    audio_block = downsample_capture_to_stt(
                        audio_block, capture_sr, stt_rate
                    )
                    duration = stt_block_duration_seconds(int(audio_block.size), stt_rate)
```

Reemplazar `silence_seconds += block_duration_seconds` y `listen_seconds += block_duration_seconds` por `+= duration`.

Dejar `block_size` para el `InputStream` Windows (`blocksize=block_size`). Linux arecord ignora ese blocksize (usa `ALSA_READ_BYTES`).

Windows: `hop_seconds=0.128` ⇒ `block_size=2048` a 16 kHz (igual que hoy). Linux: `hop_seconds=0.020` (solo afecta pre-roll/circular/VAD; arecord lee 1920 bytes).

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_mic_input.TestVadHopReal test_mic_input.TestEndpointingYCola test_mic_input.TestPiMicFijo -v
```

Expected: PASS. `NORMAL_SILENCE` 1.2 y `MAX_LISTEN` 15 no se tocan. Con hop 20 ms, 60 bloques de silencio = 1.20 s exactos.

- [ ] **Step 5: Upload producción**

`--put workers.py test_mic_input.py`. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir.

---

### Task 6: Captura persistente en `AudioWorker._run` + reescribir half-duplex

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py` (`TestMicHalfDuplex`)
- Modify: `ProyectoParaRasperrypiV5/workers.py` (`AudioWorker.__init__`, `stop`, `_run`)

**Interfaces:**
- Consumes: `AlsaCapture`, `resolve_alsa_capture_device`, `read_arecord_list`, `build_arecord_argv` (Task 1–4); `enqueue_mic_block`; `mic_open_for_listen` **solo** en `listen_until_cut`.
- Produces: captura abierta **una vez** post-LLM; Linux `AlsaCapture.start()`; Windows `InputStream.start()` fuera del loop de utterances; `set_muted(True)` (o flag equivalente) **antes** de `_handle_segment`; `_drain_audio_queue` tras el corte; `set_muted(False)` al volver a escuchar; `stop()` mata arecord. Drain thread sigue vivo durante Whisper/LLM.

- [ ] **Step 1: Write the failing tests**

Reemplazar `test_cierra_el_mic_antes_de_whisper_y_llm` en `TestMicHalfDuplex`. El contrato viejo (cerrar `InputStream` antes de Whisper) **ya no vale**: arecord recibe SIGPIPE si Python deja de leer.

```python
class TestMicHalfDuplex(unittest.TestCase):
    """El drain/callback no loguea. La captura sigue viva durante Whisper/LLM."""

    def test_callback_no_loguea_overflow(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertFalse(
            'f"Audio callback: {status}"' in src or "Audio callback:" in src,
            "el callback no debe loguear status (PortAudio no puede esperar al GIL)",
        )
        alsa = Path(__file__).resolve().parent.joinpath("alsa_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("log_action", alsa)
        self.assertNotIn("_queue_message", alsa)
        self.assertNotIn("session_policy", alsa)

    def test_captura_sigue_viva_durante_whisper_y_llm(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertNotIn("mic cerrado para STT/LLM", src)
        self.assertIn("set_muted", src)
        self.assertIn("AlsaCapture", src)
        listen_at = src.find("def listen_until_cut")
        handle_at = src.find("self._handle_segment(segment,")
        self.assertGreater(listen_at, 0)
        self.assertGreater(handle_at, listen_at)
        between = src[listen_at:handle_at]
        self.assertIn("return segment_audio", between)
        self.assertNotIn("with sd.InputStream(", between)
        self.assertNotIn("capture.stop(", between)
        self.assertNotIn("._proc.kill", between)
        after_handle = src[handle_at : handle_at + 800]
        # mute around STT/LLM, drain cola VAD, no matar arecord
        before_handle = src[handle_at - 500 : handle_at]
        self.assertIn("set_muted(True)", before_handle)
        self.assertIn("_drain_audio_queue", before_handle)

    def test_whisper_prompt_no_inyecta_que_es_eso(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertFalse(
            "¿Qué es eso?" in src,
            "el prompt de Whisper no debe incluir '¿Qué es eso?' (alucina esa frase)",
        )

    def test_callback_windows_no_importa_session_policy(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        cb_at = src.find("def callback(")
        if cb_at < 0:
            return
        # callback corto: hasta listen_until_cut o AlsaCapture
        chunk = src[cb_at : cb_at + 900]
        self.assertNotIn("from session_policy import mic_open_for_listen", chunk)
```

Borrar el método `test_cierra_el_mic_antes_de_whisper_y_llm` (el nombre nuevo es `test_captura_sigue_viva_durante_whisper_y_llm`).

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_mic_input.TestMicHalfDuplex -v
```

Expected: FAIL. Hoy el source tiene `with sd.InputStream(` entre `listen_until_cut` y `_handle_segment`, el log `mic cerrado para STT/LLM`, no hay `set_muted` ni `AlsaCapture`, y el callback hace `from session_policy import mic_open_for_listen`.

- [ ] **Step 3: Write minimal implementation**

En `AudioWorker.__init__` añadir:

```python
        self._alsa_capture: Any = None
        self._input_stream: Any = None
```

En `AudioWorker.stop`:

```python
    def stop(self) -> None:
        log_action("AudioWorker", "deteniendo...")
        self._stop_event.set()
        cap = self._alsa_capture
        if cap is not None:
            try:
                cap.stop()
            except Exception:
                pass
        stream = self._input_stream
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._flush_vocab_parent_alert(force_session=True)
        log_action("AudioWorker", "detenido")
```

Reestructurar `_run` **después** de cargar Whisper/LLM/VAD y del early-return `microphone_device_index == -1`.

Quitar el `callback` que importa `session_policy`. Dejar `listen_until_cut` casi igual (ya con duración real de Task 5 y `mic_open_for_listen` en el hilo VAD).

Reemplazar el `while` que abre `with sd.InputStream(...)` **por utterance** por esto (misma cola `audio_queue`, `drop_hits`, `overflow_hits`):

```python
            echo_until = [self._echo_mute_until]

            def _speaker_busy() -> bool:
                return self.speech_worker is not None and self.speech_worker.is_busy()

            def _sync_echo_until() -> None:
                echo_until[0] = self._echo_mute_until

            use_alsa = sys.platform.startswith("linux")
            capture = None
            input_stream = None
            if capture_sr != stt_rate:
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"AudioWorker: mic {capture_sr} Hz → STT {stt_rate} Hz (fuera del callback)",
                )
            mic_label = f"{self.microphone_device_index} activo"

            if use_alsa:
                from alsa_capture import (
                    AlsaCapture,
                    ENV_ALSA_CAPTURE_DEVICE,
                    read_arecord_list,
                    resolve_alsa_capture_device,
                )

                sd_name = ""
                try:
                    info = sd.query_devices(self.microphone_device_index)
                    sd_name = str(info.get("name") or "")
                except Exception:
                    sd_name = ""
                device = resolve_alsa_capture_device(
                    env=os.environ,
                    arecord_l=read_arecord_list(),
                    sounddevice_name=sd_name,
                )
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"AudioWorker: arecord {device} 48k S16_LE (env {ENV_ALSA_CAPTURE_DEVICE} override si está)",
                )
                capture = AlsaCapture(
                    device=device,
                    audio_queue=audio_queue,
                    drop_hits=drop_hits,
                    stop_event=self._stop_event,
                    enqueue=enqueue_mic_block,
                    speaker_busy=_speaker_busy,
                    echo_until=echo_until,
                )
                self._alsa_capture = capture
                capture.start()
                if capture.pipe_size:
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"AudioWorker: pipe_size={capture.pipe_size}",
                    )
                if capture.negotiated:
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"AudioWorker: ALSA negociado {capture.negotiated}",
                    )
            else:

                def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
                    if status:
                        overflow_hits[0] += 1
                    if capture_muted[0] or _speaker_busy() or time.monotonic() < echo_until[0]:
                        return
                    audio_block = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
                    enqueue_mic_block(audio_queue, audio_block, drop_hits)

                capture_muted = [False]
                input_stream = sd.InputStream(
                    device=self.microphone_device_index,
                    channels=1,
                    samplerate=capture_sr,
                    blocksize=block_size,
                    dtype="float32",
                    callback=callback,
                )
                self._input_stream = input_stream
                input_stream.start()

            try:
                while not self._stop_event.is_set():
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "status",
                        {"mic": mic_label, "volume": 0},
                    )
                    vad_tag = vad_log_label(getattr(vad, "_mode", "energy"))
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"{vad_tag}: escuchando...",
                    )
                    overflow_hits[0] = 0
                    drop_hits[0] = 0
                    overrun_before = capture.overrun_hits if capture is not None else 0
                    if capture is not None:
                        capture.set_muted(False)
                    else:
                        capture_muted[0] = False
                    _sync_echo_until()
                    segment = listen_until_cut()
                    if capture is not None:
                        n_xrun = capture.overrun_hits - overrun_before
                        n_drop = drop_hits[0]
                        n_restart = capture.restarts
                        n_busy = capture.busy_hits
                        capture.set_muted(True)
                    else:
                        n_xrun = overflow_hits[0]
                        n_drop = drop_hits[0]
                        n_restart = 0
                        n_busy = 0
                        capture_muted[0] = True
                    overflow_hits[0] = 0
                    drop_hits[0] = 0
                    if n_xrun:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: {n_xrun} overruns/xruns ALSA (captura sigue viva)",
                        )
                        log_action("AudioWorker", f"{n_xrun} overruns/xruns ALSA")
                    if n_drop:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: {n_drop} bloques descartados (cola llena)",
                        )
                        log_action("AudioWorker", f"{n_drop} bloques descartados (cola llena)")
                    if n_restart:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: arecord reiniciado {n_restart} veces",
                        )
                    if n_busy:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            "AudioWorker: hw: busy (ver LATENCIA PipeWire; lsof /dev/snd/pcmC*D0c)",
                        )
                    self._drain_audio_queue(audio_queue)
                    if self._stop_event.is_set():
                        break
                    if segment is not None and segment.size:
                        self._handle_segment(segment, whisper_model, audio_queue)
                    _sync_echo_until()
            finally:
                if capture is not None:
                    capture.stop()
                    self._alsa_capture = None
                if input_stream is not None:
                    try:
                        input_stream.stop()
                    except Exception:
                        pass
                    try:
                        input_stream.close()
                    except Exception:
                        pass
                    self._input_stream = None
```

El `try/except Exception` que hoy envuelve todo `_run` (log `Error en micrófono`) se mantiene **alrededor** de este bloque. El `finally` de “tarea _run finalizada” se queda.

`_silence_mic_after_speaker` ya drena la cola y setea `_echo_mute_until`. Llamarlo sigue dentro de `_handle_segment` (no mover). `_sync_echo_until` copia ese valor a `echo_until[0]` para que el drain (lista compartida) vea la ventana de eco **sin** importar `session_policy`.

Importar `os` en `workers.py` si aún no está (ya se usa en el archivo; verificar). `AlsaCapture` se importa **lazy** dentro de `_run` para no romper tests Windows que mockean `sounddevice`.

Si `resolve_alsa_capture_device` lanza `ValueError`, dejar que el `except` existente de `_run` loguee `Error en micrófono: …`.

Asegurar que `listen_until_cut` **no** está indentado dentro de `with sd.InputStream`.

`test_endpointing` busca este string exacto — **no romperlo**:

```python
"audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_mic_input test_alsa_capture -v
```

Expected: PASS. En particular `TestMicHalfDuplex.test_captura_sigue_viva_durante_whisper_y_llm` y `test_callback_windows_no_importa_session_policy`.

- [ ] **Step 5: Upload producción**

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put ProyectoParaRasperrypiV5/workers.py ProyectoParaRasperrypiV5/alsa_capture.py ProyectoParaRasperrypiV5/test_mic_input.py ProyectoParaRasperrypiV5/test_alsa_capture.py
```

No arrancar `app.py`. Avisar a Teo que hay que **reiniciar** el proceso que ya corre.

- [ ] **Step 6: Skip commit**

Omitir.

---

### Task 7: Docs (Agents + LATENCIA) — PipeWire, grupo audio, no v1

**Files:**
- Modify: `ProyectoParaRasperrypiV5/Agents.md` (línea de Audio Captura)
- Modify: `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md`

**Interfaces:**
- Consumes: comportamiento de Tasks 1–6.
- Produces: documentación de operación. No código.

- [ ] **Step 1: Write the failing tests** (docs vía source assert mínimo en `test_mic_input` o skip tests y editar docs; este plan usa un assert corto para no dejar la captura sin mención)

Añadir en `test_mic_input.py`:

```python
class TestDocsArecord(unittest.TestCase):
    def test_agents_menciona_arecord(self) -> None:
        text = Path(__file__).resolve().parent.joinpath("Agents.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("arecord", text)
        self.assertIn("hw:CARD=", text)
        self.assertIn("ALSA_CAPTURE_DEVICE", text)

    def test_latencia_documenta_pipewire_y_no_sudo(self) -> None:
        text = Path(__file__).resolve().parent.joinpath(
            "docs", "LATENCIA_AUDIO_CAMARA.md"
        ).read_text(encoding="utf-8")
        self.assertIn("arecord", text)
        self.assertIn("lsof", text)
        self.assertIn("pipewire", text.lower())
        self.assertIn("grupo audio", text.lower())
        self.assertNotIn("dwc_otg", text)
        self.assertNotIn("PA_ALSA_PLUGHW", text)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_mic_input.TestDocsArecord -v
```

Expected: FAIL (Agents sigue diciendo solo sounddevice; LATENCIA no tiene la sección).

- [ ] **Step 3: Write the docs**

En `Agents.md`, reemplazar la viñeta **Audio (Captura)** por:

```markdown
- **Audio (Captura):** Linux (Pi 5): `arecord` persistente `-D hw:CARD=…,DEV=0 -t raw -f S16_LE -c 1 -r 48000` (override `ALSA_CAPTURE_DEVICE`). El hilo drain no se detiene en TTS/Whisper/LLM; mute = no encolar al VAD. Downsample 48→16 (promedio de 3) fuera del drain. Windows: `sounddevice` InputStream a 16 kHz. Playback (otra tarjeta): `sounddevice` OutputStream. En la Pi 5 el VAD es energía RMS (Silero no se carga en aarch64: Bus error). En Windows, `silero-vad` si está disponible.
```

En `LATENCIA_AUDIO_CAMARA.md` añadir sección **después** de “### 11. Cola USB y downsample” (texto a pegar; los comandos van en bloque indentado, no fence anidado):

### 12. arecord persistente (2026-09-08)

- Linux: ya no se abre `sd.InputStream` por cada frase. Un `arecord` a `hw:CARD=…,DEV=0` (no `plughw`, no WAV, no 16 kHz en hw) queda vivo todo el `AudioWorker`.
- Lectura: 1920 bytes (960 frames @ 48 kHz = 20 ms). VAD suma la duración real del bloque (no 0.128 s fijos). Pre-roll ~1 s = 50 bloques; circular ~6 s = 300 bloques.
- Mute durante Whisper/LLM/TTS: se sigue leyendo el pipe (si no, SIGPIPE). No se encola al VAD. Tras el segmento se drena la cola.
- Watchdog: EOF o proceso muerto → restart. Stderr cuenta `overrun` / `busy`. Sin `--fatal-errors`, sin `-q`.
- `pipesize` 1 MiB, fallback 64 KiB. Usuario `teo` en grupo `audio`. **Sin sudo.**
- Override: `ALSA_CAPTURE_DEVICE=hw:CARD=Device,DEV=0`.
- Pedido ALSA: `--period-time=20000 --buffer-time=500000`; el log muestra lo negociado.
- **Síntoma si hw: está busy:** arecord stderr `Device or resource busy`. **No asumir PipeWire.** Primero: `lsof /dev/snd/pcmC*D0c` (y `fuser` si hace falta). Si el proceso es `pipewire` / `wireplumber` / `pipewire-pulse`, mask **manual** (no desde `app.py`):

      systemctl --user status pipewire wireplumber pipewire-pulse
      # solo si lsof confirmó que son ellos quienes tienen el PCM de captura:
      systemctl --user mask --now pipewire.socket pipewire.service wireplumber.service pipewire-pulse.service

  Rollback: `systemctl --user unmask …` y volver a arrancar. El parlante puede ser otra tarjeta; no maskear a ciegas.
- **No v1:** soxr, `nice -10`, pyalsaaudio, udev, `--fatal-errors`.
- **No usar como fix:** `dwc_otg`, `PA_ALSA_PLUGHW`, forzar 16 kHz en `hw:`.
- Playback sigue en `sounddevice` OutputStream.
- **Revertir:** volver a `with sd.InputStream` por utterance en `workers.py` y borrar `alsa_capture.py`.

En regla 4 de Agents (silencios) no hace falta cambiar 1.2 / 15.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_mic_input.TestDocsArecord test_mic_input test_alsa_capture -v
```

Expected: PASS.

- [ ] **Step 5: Upload producción**

`--put Agents.md` (LATENCIA está en `docs/` y `sftp_to_pi.py` usa solo el basename: **no** subirlo con ese script o quedaría en el root remoto). Agents sí corre como contexto en la Pi. LATENCIA es doc local. No arrancar `app.py`.

- [ ] **Step 6: Skip commit**

Omitir.

---

## Orden y verificación final

Correr desde `ProyectoParaRasperrypiV5`:

```bash
python -m unittest test_alsa_capture test_mic_input -v
```

Expected: PASS. No pytest. No `git commit`. No `app.py`.

Smoke **solo si Teo pide** reiniciar la app en la Pi: un “hola” no debe matar arecord (el proceso `arecord` permanece en `ps` durante Whisper). Overruns se loguean **después** del corte, no desde el drain.

---

## Cobertura critic → tarea

| Requisito | Tarea |
|---|---|
| arecord persistente `hw:CARD=…,DEV=0` raw S16 48 kHz mono | 1, 2, 6 |
| no WAV / plughw / `-r 16000` / default `hw:1,0` | 1, 2 |
| period-time 20000, buffer-time 500000, log negociado | 2, 4, 6 |
| drain nunca para; mute = no encolar; SIGPIPE si se deja de leer | 3, 6 |
| Windows sounddevice 16 kHz | 5 (hop 0.128), 6 (InputStream) |
| downsample fuera del read; múltiplo de 3; read(1920) | 2, 3, 5 |
| VAD duración real; pre-roll/circular | 5 |
| reescribir test close-before-whisper; drain sin log | 6, 3 |
| watchdog EOF+poll; stderr overrun/busy; no `--fatal-errors`; no `-q` | 4 |
| PipeWire documentar + lsof; no asumir | 7 |
| pipesize 1 MiB / 64 KiB | 4 |
| no sudo; grupo audio | 1 (argv), 7 (docs) |
| NORMAL_SILENCE 1.2, MAX_LISTEN 15, energy aarch64 | 5 (no tocar valores) |
| no v1: soxr, nice, pyalsaaudio, udev | 7 |
| no dwc_otg / PA_ALSA_PLUGHW / 16 kHz en hw | 2, 7 |
| env `ALSA_CAPTURE_DEVICE` | 1, 6 |
| playback OutputStream intacto | 6 (no tocar SpeechWorker play) |
| TDD unittest; upload; no commit; no app.py | Global + cada task |

## Notas para el implementador

- `alsa_capture.py` **no** importa `workers` (ciclo). `enqueue_mic_block` se pasa como callable.
- Tests de `arecord -l` usan el dump fake; no invocar `arecord` real en Windows.
- `select.select` sobre pipes **no** funciona en Windows; `_read_chunk` está detrás de tests de `should_restart_arecord` (sin abrir pipes reales).
- Si Teo pide ejecutar: usar `executing-plans` en esta sesión, o un subagente por tarea con `subagent-driven-development`.
