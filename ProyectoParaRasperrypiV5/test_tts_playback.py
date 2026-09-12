"""Tests de negociación de formato de audio para TTS en Raspberry Pi.

Reproduce PaErrorCode -9994: ALSA rechaza float32/mono y exige int16/estéreo.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from workers import SpeechWorker


class _Unsupported(Exception):
    pass


def _check_pi_alsa(**kwargs):
    """Simula un dispositivo ALSA típico de Raspberry Pi.

    Acepta solo int16, 2 canales y 48000/44100 Hz.
    """
    if kwargs.get("dtype") == "float32":
        raise _Unsupported("Sample format not supported")
    if kwargs.get("channels") != 2:
        raise _Unsupported("Invalid number of channels")
    if kwargs.get("samplerate") not in (44100.0, 48000.0):
        raise _Unsupported("Invalid sample rate")


class TestFindSupportedOutputConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = SpeechWorker(output_device_index=0)

    def test_pi_alsa_elige_int16_estereo_48k(self) -> None:
        with patch("workers.sd.check_output_settings", side_effect=_check_pi_alsa):
            sr, dtype, channels = self.worker._find_supported_output_config(22050, 1)
        self.assertEqual(sr, 48000)
        self.assertEqual(dtype, "int16")
        self.assertEqual(channels, 2)

    def test_linux_usa_48k_int16_estereo_sin_probe(self) -> None:
        mock_check = MagicMock(side_effect=AssertionError("no probe"))
        with patch("workers.sys.platform", "linux"), patch(
            "workers.sd.check_output_settings", mock_check
        ):
            sr, dtype, channels = self.worker._find_supported_output_config(22050, 1)
        self.assertEqual(sr, 48000)
        self.assertEqual(dtype, "int16")
        self.assertEqual(channels, 2)
        mock_check.assert_not_called()

    def test_windows_mantiene_float32_mono_si_el_dispositivo_lo_acepta(self) -> None:
        with patch("workers.sys.platform", "win32"), patch(
            "workers.sd.check_output_settings", return_value=None
        ):
            sr, dtype, channels = self.worker._find_supported_output_config(22050, 1)
        self.assertEqual(sr, 22050)
        self.assertEqual(dtype, "float32")
        self.assertEqual(channels, 1)

    def test_si_nada_pasa_el_probe_cae_a_int16_estereo_48k(self) -> None:
        with patch("workers.sd.check_output_settings", side_effect=_Unsupported("nope")):
            sr, dtype, channels = self.worker._find_supported_output_config(22050, 1)
        self.assertEqual(sr, 48000)
        self.assertEqual(dtype, "int16")
        self.assertEqual(channels, 2)


class TestAdaptPlaybackAudio(unittest.TestCase):
    def test_mono_float_a_estereo_int16_resampleado(self) -> None:
        audio = np.zeros((22050, 1), dtype=np.float32)
        audio[0, 0] = 1.0
        adapted, sr = SpeechWorker._adapt_playback_audio(
            audio, orig_sr=22050, target_sr=48000, target_dtype="int16", target_channels=2
        )
        self.assertEqual(sr, 48000)
        self.assertEqual(adapted.dtype, np.int16)
        self.assertEqual(adapted.shape[1], 2)
        self.assertGreater(adapted.shape[0], 22050)
        self.assertEqual(adapted[0, 0], adapted[0, 1])


class TestPlayRetriesInt16(unittest.TestCase):
    def test_reintenta_int16_estereo_si_float32_falla_al_abrir(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        audio = np.zeros(1000, dtype=np.float32)
        opened = []

        class _Stream:
            def __init__(self, **kwargs):
                opened.append(kwargs)
                if kwargs.get("dtype") == "float32":
                    raise RuntimeError(
                        "Error opening OutputStream: Sample format not supported [PaErrorCode -9994]"
                    )
                self.callback = kwargs.get("callback")
                self.channels = kwargs.get("channels", 1)
                self.dtype = kwargs.get("dtype", "float32")

            def __enter__(self):
                frames = 512
                dt = np.int16 if self.dtype == "int16" else np.float32
                outdata = np.zeros((frames, self.channels), dtype=dt)
                try:
                    while True:
                        self.callback(outdata, frames, None, None)
                except Exception:
                    pass
                return self

            def __exit__(self, *args):
                return False

        with patch.object(
            worker, "_find_supported_output_config", return_value=(22050, "float32", 1)
        ), patch("workers.sd.OutputStream", side_effect=_Stream), patch.object(
            worker, "_log"
        ):
            worker._play_wav_via_output_stream(audio, 22050)

        dtypes = [cfg.get("dtype") for cfg in opened]
        self.assertIn("float32", dtypes)
        self.assertIn("int16", dtypes)
        last = opened[-1]
        self.assertEqual(last["dtype"], "int16")
        self.assertEqual(last["channels"], 2)


class TestStorySentencePipeline(unittest.TestCase):
    def test_workers_pipeline_el_chunk_del_cuento(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        pipeline_at = src.find("speak_sentences_and_wait")
        self.assertGreater(pipeline_at, 0)
        speak_chunk = src.find("speak_sentences_and_wait(chunk")
        self.assertGreater(speak_chunk, 0)

    def test_piper_sintetiza_la_siguiente_mientras_suena_la_actual(self) -> None:
        import threading
        import time

        worker = SpeechWorker(output_device_index=0)
        worker._piper_voice = object()
        order: list[str] = []
        play_started = threading.Event()
        play_release = threading.Event()

        def synth(text: str, length_scale: float | None = None):
            order.append(f"synth:{text}")
            return (np.zeros(8, dtype=np.float32), 22050)

        def play(_audio, _sr):
            order.append("play-start")
            play_started.set()
            play_release.wait(timeout=1.0)
            order.append("play-end")

        with patch.object(worker, "_synthesize_piper_pcm", side_effect=synth), patch.object(
            worker, "_play_wav_via_output_stream", side_effect=play
        ):
            def _run() -> None:
                worker._speak_sentence_pipeline(["Uno.", "Dos.", "Tres."])

            t = threading.Thread(target=_run)
            t.start()
            self.assertTrue(play_started.wait(timeout=1.0))
            deadline = time.monotonic() + 1.0
            while "synth:Dos." not in order and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("synth:Dos.", order)
            play_release.set()
            t.join(timeout=2.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(order[0], "synth:Uno.")
        self.assertIn("synth:Dos.", order)
        self.assertLess(order.index("synth:Dos."), order.index("play-end"))


class TestStoryTtsGuard(unittest.TestCase):
    def test_cola_extra_se_tira_durante_el_cuento(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker.set_story_guard(True)
        worker.speak_and_wait("No te escuché bien, ¿me lo decís de nuevo?")
        self.assertTrue(worker._queue.empty())

    def test_tts_del_cuento_si_entra(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker.set_story_guard(True)
        worker.speak_and_wait("¿Seguimos?", timeout=0.01, story=True)
        self.assertFalse(worker._queue.empty())
        self.assertEqual(worker._queue.get_nowait(), "¿Seguimos?")

    def test_speak_suelto_tambien_se_tira(self) -> None:
        worker = SpeechWorker(output_device_index=0)
        worker.set_story_guard(True)
        worker.speak("¿Cuál animal tiene más trocitos?")
        self.assertTrue(worker._queue.empty())


if __name__ == "__main__":
    unittest.main()
