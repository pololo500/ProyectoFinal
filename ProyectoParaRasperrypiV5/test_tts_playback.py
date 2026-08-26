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

    def test_windows_mantiene_float32_mono_si_el_dispositivo_lo_acepta(self) -> None:
        with patch("workers.sd.check_output_settings", return_value=None):
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


if __name__ == "__main__":
    unittest.main()
