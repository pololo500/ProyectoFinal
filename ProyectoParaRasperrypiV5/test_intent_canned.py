"""Tests livianos de rotación de respuestas y utterances cortos."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import IntentDispatcher


class TestCannedRotation(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = IntentDispatcher.__new__(IntentDispatcher)
        self.dispatcher._last_canned = {}

    def test_no_repite_si_hay_alternativa(self) -> None:
        seen = set()
        for _ in range(8):
            seen.add(self.dispatcher._pick_response("greeting", ["A", "B"]))
        self.assertEqual(seen, {"A", "B"})

    def test_si_corto_no_es_enojo(self) -> None:
        self.assertTrue(self.dispatcher._utterance_too_thin("Sí.", "emotion_angry"))
        self.assertFalse(self.dispatcher._utterance_too_thin("estoy enojado", "emotion_angry"))


if __name__ == "__main__":
    unittest.main()
