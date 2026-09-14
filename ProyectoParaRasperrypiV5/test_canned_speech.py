"""Tests TDD del clip pregrabado y del gate de TTS dormido."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import SpeechWorker


class TestCannedClipAndSleepGate(unittest.TestCase):
    def test_play_canned_file_ausente_es_false(self) -> None:
        worker = SpeechWorker()
        self.assertFalse(worker.play_canned_file(Path("/no/existe/todavia_no_estoy_listo.wav")))

    def test_speak_no_encola_si_gate_dormido(self) -> None:
        worker = SpeechWorker()
        worker.set_power_gate(lambda: False)
        worker.speak("hola")
        self.assertTrue(worker._queue.empty())

    def test_speak_allow_when_asleep_encola(self) -> None:
        worker = SpeechWorker()
        worker.set_power_gate(lambda: False)
        worker.speak("Hoy ya jugamos bastante. Descansemos un rato.", allow_when_asleep=True)
        self.assertFalse(worker._queue.empty())

    def test_speak_no_encola_un_segundo_pedido_de_abrazo(self) -> None:
        worker = SpeechWorker()
        phrase = "Quiero un abrazo. ¿Me das uno?"
        worker.speak(phrase)
        worker.speak(phrase)
        self.assertEqual(worker._queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
