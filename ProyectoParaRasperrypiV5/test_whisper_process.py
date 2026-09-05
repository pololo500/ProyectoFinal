"""Tests de Whisper aislado (sin cargar faster-whisper)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from whisper_process import (
    RemoteWhisper,
    child_force_cpu_isa,
    default_compute_type,
    is_bus_exit,
    stt_empty_log,
    whisper_cpu_threads,
    whisper_model_candidates,
)


class TestWhisperDefaults(unittest.TestCase):
    def test_aarch64_usa_float32(self) -> None:
        with patch("whisper_process.platform.machine", return_value="aarch64"):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(default_compute_type(), "float32")

    def test_x86_usa_int8(self) -> None:
        with patch("whisper_process.platform.machine", return_value="x86_64"):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(default_compute_type(), "int8")

    def test_override_whisper_compute(self) -> None:
        with patch("whisper_process.platform.machine", return_value="aarch64"):
            with patch.dict("os.environ", {"WHISPER_COMPUTE": "int8"}):
                self.assertEqual(default_compute_type(), "int8")

    def test_hilos_por_defecto_son_dos(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(whisper_cpu_threads(), 2)

    def test_aarch64_no_fuerza_isa(self) -> None:
        with patch("whisper_process.platform.machine", return_value="aarch64"):
            with patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(child_force_cpu_isa())

    def test_x86_no_fuerza_isa(self) -> None:
        with patch("whisper_process.platform.machine", return_value="x86_64"):
            with patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(child_force_cpu_isa())


class TestWhisperFallback(unittest.TestCase):
    def test_medium_cae_a_small_y_tiny(self) -> None:
        self.assertEqual(
            whisper_model_candidates("medium"),
            ("medium", "small", "tiny"),
        )

    def test_si_pide_small_no_intenta_medium(self) -> None:
        self.assertEqual(whisper_model_candidates("small"), ("small", "tiny"))

    def test_exit_menos_siete_es_sigbus(self) -> None:
        self.assertTrue(is_bus_exit(-7))
        self.assertFalse(is_bus_exit(1))

    def test_sin_whisper_el_log_no_dice_que_no_hubo_texto(self) -> None:
        msg = stt_empty_log(whisper_available=False, elapsed_ms=0)
        self.assertIn("Sin Whisper", msg)
        self.assertNotIn("no se detectó texto", msg)

    def test_paginas_16k_no_son_compatibles(self) -> None:
        from whisper_process import ctranslate2_compatible

        with patch("whisper_process.kernel_page_size", return_value=16384):
            self.assertFalse(ctranslate2_compatible())

    def test_paginas_4k_son_compatibles(self) -> None:
        from whisper_process import ctranslate2_compatible

        with patch("whisper_process.kernel_page_size", return_value=4096):
            self.assertTrue(ctranslate2_compatible())


class TestRemoteWhisper(unittest.TestCase):
    def test_transcribe_arma_segmentos(self) -> None:
        class _Q:
            def __init__(self) -> None:
                self.sent = None

            def put(self, item) -> None:
                self.sent = item

            def get(self, timeout: float = 0):
                return (
                    "ok",
                    [{"text": "hola", "avg_logprob": -0.2, "no_speech_prob": 0.1}],
                )

        remote = RemoteWhisper(process=SimpleNamespace(is_alive=lambda: True), req=_Q(), res=_Q())
        segments, info = remote.transcribe([0.0], language="es")
        self.assertIsNone(info)
        self.assertEqual(segments[0].text, "hola")
        self.assertEqual(segments[0].avg_logprob, -0.2)


if __name__ == "__main__":
    unittest.main()
