"""Captura ALSA persistente: device string, arecord argv, drain, watchdog."""
from __future__ import annotations

import os
import queue
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from alsa_capture import (
    ALSA_BUFFER_TIME_US,
    ALSA_FRAMES_PER_READ,
    ALSA_PERIOD_TIME_US,
    ALSA_RATE,
    ALSA_READ_BYTES,
    ENV_ALSA_CAPTURE_DEVICE,
    PIPE_SIZE_FALLBACK,
    PIPE_SIZE_PREFERRED,
    AlsaCapture,
    AlsaCard,
    apply_pipe_size,
    arecord_list_argv,
    build_arecord_argv,
    consume_raw_pcm,
    hw_device_string,
    match_card_for_sounddevice_name,
    note_arecord_stderr_line,
    parse_arecord_cards,
    pcm_s16le_bytes_to_int16,
    resolve_alsa_capture_device,
    should_restart_arecord,
)
from workers import enqueue_mic_block

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

    def test_parcial_muted_no_se_combina_despues_de_unmute(self) -> None:
        q: queue.Queue = queue.Queue()
        drops = [0]
        leftover = consume_raw_pcm(
            b"\x01" * 1000,
            True,
            q,
            drops,
            enqueue_mic_block,
        )
        leftover = consume_raw_pcm(
            b"\x02" * 920,
            False,
            q,
            drops,
            enqueue_mic_block,
            leftover=leftover,
        )
        self.assertTrue(q.empty())
        self.assertEqual(leftover, b"\x02" * 920)

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

    def test_mute_espera_consume_y_limpia_leftover(self) -> None:
        cap = self._cap()
        cap._proc = MagicMock()
        cap._proc.poll.return_value = None
        consume_started = threading.Event()
        release_consume = threading.Event()
        mute_started = threading.Event()
        mute_done = threading.Event()

        def fake_consume(*args, **kwargs) -> bytes:
            consume_started.set()
            self.assertTrue(release_consume.wait(timeout=1.0))
            cap._stop_event.set()
            return b"audio-muted"

        def mute() -> None:
            mute_started.set()
            cap.set_muted(True)
            mute_done.set()

        with (
            patch.object(cap, "_read_chunk", return_value=b"\x01\x02"),
            patch("alsa_capture.consume_raw_pcm", side_effect=fake_consume),
        ):
            drain = threading.Thread(target=cap._drain_loop)
            drain.start()
            self.assertTrue(consume_started.wait(timeout=1.0))
            setter = threading.Thread(target=mute)
            setter.start()
            self.assertTrue(mute_started.wait(timeout=1.0))
            mute_was_blocked = not mute_done.wait(timeout=0.1)
            release_consume.set()
            drain.join(timeout=1.0)
            setter.join(timeout=1.0)

        self.assertTrue(mute_was_blocked)
        self.assertFalse(drain.is_alive())
        self.assertFalse(setter.is_alive())
        self.assertEqual(cap._leftover, b"")

    def test_start_es_idempotente(self) -> None:
        cap = self._cap()
        thread = MagicMock()
        with (
            patch.object(cap, "_spawn") as spawn,
            patch("alsa_capture.threading.Thread", return_value=thread) as thread_cls,
        ):
            cap.start()
            cap.start()
        spawn.assert_called_once_with()
        self.assertEqual(thread_cls.call_count, 2)
        self.assertEqual(thread.start.call_count, 2)

    def test_stop_espera_drain_y_stderr(self) -> None:
        cap = self._cap()
        drain = MagicMock()
        stderr = MagicMock()
        cap._drain_thread = drain
        cap._stderr_thread = stderr
        cap.stop()
        drain.join.assert_called_once_with(timeout=1.0)
        stderr.join.assert_called_once_with(timeout=1.0)

    def test_stop_mata_proceso_creado_mientras_espera_hilos(self) -> None:
        cap = self._cap()
        replacement = MagicMock()
        drain = MagicMock()
        drain.join.side_effect = lambda timeout: setattr(cap, "_proc", replacement)
        cap._drain_thread = drain

        cap.stop()

        replacement.kill.assert_called_once_with()
        self.assertIsNone(cap._proc)


class TestWatchdogYStderr(unittest.TestCase):
    def _cap(self) -> AlsaCapture:
        return AlsaCapture(
            device="hw:CARD=Device,DEV=0",
            audio_queue=queue.Queue(),
            drop_hits=[0],
            stop_event=threading.Event(),
            enqueue=enqueue_mic_block,
        )

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

    def test_restart_no_spawn_si_stop_se_activa_durante_backoff(self) -> None:
        cap = self._cap()

        def stop_during_sleep(_seconds: float) -> None:
            cap._stop_event.set()

        with (
            patch("alsa_capture.time.sleep", side_effect=stop_during_sleep),
            patch.object(cap, "_spawn") as spawn,
        ):
            cap._restart()

        spawn.assert_not_called()

    def test_restart_cierra_pipes_del_proceso_anterior(self) -> None:
        cap = self._cap()
        old = MagicMock()
        cap._proc = old

        with (
            patch("alsa_capture.time.sleep", side_effect=lambda _seconds: cap._stop_event.set()),
            patch.object(cap, "_spawn"),
        ):
            cap._restart()

        old.stdout.close.assert_called_once_with()
        old.stderr.close.assert_called_once_with()

    def test_drain_reintenta_si_spawn_lanza_oserror(self) -> None:
        cap = self._cap()
        attempts = 0
        errors: list[BaseException] = []

        def flaky_spawn() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("arecord no disponible")
            cap._stop_event.set()

        def run_drain() -> None:
            try:
                cap._drain_loop()
            except BaseException as exc:
                errors.append(exc)

        with (
            patch("alsa_capture.time.sleep", return_value=None),
            patch.object(cap, "_spawn", side_effect=flaky_spawn),
        ):
            drain = threading.Thread(target=run_drain)
            drain.start()
            drain.join(timeout=1.0)

        self.assertFalse(drain.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 2)

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


if __name__ == "__main__":
    unittest.main()
