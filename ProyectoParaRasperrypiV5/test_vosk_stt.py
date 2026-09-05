"""Tests del STT Vosk (sin bajar el modelo)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from vosk_stt import text_from_vosk_json


class TestVoskJson(unittest.TestCase):
    def test_lee_el_campo_text(self) -> None:
        self.assertEqual(text_from_vosk_json('{"text": "hola teo"}'), "hola teo")

    def test_vacio_si_no_hay_texto(self) -> None:
        self.assertEqual(text_from_vosk_json("{}"), "")

    def test_transcriber_arma_segmento(self) -> None:
        from vosk_stt import VoskTranscriber

        class _Rec:
            def __init__(self) -> None:
                self.chunks: list[int] = []

            def AcceptWaveform(self, pcm: bytes) -> bool:
                self.chunks.append(len(pcm))
                return False

            def FinalResult(self) -> str:
                return '{"text": "quiero jugar"}'

        rec = _Rec()
        model = SimpleNamespace()
        worker = VoskTranscriber(model)
        worker._recognizer_factory = lambda _model, _sr: rec
        segments, info = worker.transcribe([0.1, -0.1, 0.2])
        self.assertIsNone(info)
        self.assertEqual(segments[0].text, "quiero jugar")
        self.assertTrue(sum(rec.chunks) > 0)

    def test_audio_largo_se_parte_en_varios_bloques(self) -> None:
        from vosk_stt import VOSK_PCM_CHUNK, VoskTranscriber

        class _Rec:
            def __init__(self) -> None:
                self.n = 0

            def AcceptWaveform(self, pcm: bytes) -> bool:
                self.n += 1
                return False

            def FinalResult(self) -> str:
                return '{"text": "hola"}'

        rec = _Rec()
        worker = VoskTranscriber(SimpleNamespace())
        worker._recognizer_factory = lambda _model, _sr: rec
        samples = (VOSK_PCM_CHUNK // 2) * 3 + 10
        worker.transcribe(np.zeros(samples, dtype=np.float32))
        self.assertGreaterEqual(rec.n, 2)


if __name__ == "__main__":
    unittest.main()
