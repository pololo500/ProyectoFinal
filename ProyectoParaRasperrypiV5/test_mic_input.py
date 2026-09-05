"""Micrófono USB local: negociar sample rate (PaErrorCode -9997) y sin puente TCP."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from workers import find_supported_input_config, mic_block_to_stt


class _Unsupported(Exception):
    pass


def _check_usb_pnp(**kwargs):
    """USB PnP típico: no abre a 16 kHz (el error de la captura)."""
    if kwargs.get("samplerate") not in (44100.0, 48000.0):
        raise _Unsupported("Invalid sample rate [PaErrorCode -9997]")
    if kwargs.get("channels") not in (1, 2):
        raise _Unsupported("Invalid number of channels")


class TestFindSupportedInputConfig(unittest.TestCase):
    def test_usb_pnp_elige_48k_si_16k_falla(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 48000.0}
        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", side_effect=_check_usb_pnp
        ):
            sr, dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(sr, 48000)
        self.assertEqual(channels, 1)
        self.assertEqual(dtype, "float32")

    def test_si_16k_anda_lo_deja(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 16000.0}
        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", return_value=None
        ):
            sr, dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(sr, 16000)
        self.assertEqual(dtype, "float32")
        self.assertEqual(channels, 1)

    def test_no_pide_mas_canales_que_el_dispositivo(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 44100.0}
        seen: list[int] = []

        def _check(**kwargs):  # noqa: ANN003
            ch = int(kwargs.get("channels") or 0)
            seen.append(ch)
            if ch > 1:
                raise AssertionError("ALSA: channelCount <= maxChans")
            if kwargs.get("samplerate") == 16000.0:
                raise _Unsupported("Invalid sample rate")

        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", side_effect=_check
        ):
            sr, _dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(channels, 1)
        self.assertEqual(sr, 44100)
        self.assertTrue(seen)
        self.assertTrue(all(ch <= 1 for ch in seen))


class TestMicBlockToStt(unittest.TestCase):
    def test_bloque_48k_queda_en_16k(self) -> None:
        frames_48k = int(48000 * 0.128)
        indata = np.zeros((frames_48k, 1), dtype=np.float32)
        out = mic_block_to_stt(indata, capture_sr=48000, target_sr=16000)
        self.assertEqual(len(out), int(16000 * 0.128))
        self.assertEqual(out.dtype, np.float32)

    def test_int16_estereo_pasa_a_float_mono(self) -> None:
        frames = 100
        stereo = np.zeros((frames, 2), dtype=np.int16)
        stereo[:, 0] = 16384
        out = mic_block_to_stt(stereo, capture_sr=16000, target_sr=16000)
        self.assertEqual(len(out), frames)
        self.assertAlmostEqual(float(out[0]), 0.5, delta=0.01)


class TestNoPuenteMicPc(unittest.TestCase):
    def test_cli_no_tiene_mic_tcp(self) -> None:
        from app import build_arg_parser

        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--mic-tcp"])

    def test_workers_no_abre_tcp_de_la_pc(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mic_tcp", src)
        self.assertNotIn("run_mic_tcp_server", src)


if __name__ == "__main__":
    unittest.main()
