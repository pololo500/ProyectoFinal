"""Tests TDD de yoga guiado multi-paso."""
from __future__ import annotations

import unittest

from yoga_engine import YogaEngine


class TestYogaEngine(unittest.TestCase):
    def test_inicia_primera_postura(self) -> None:
        engine = YogaEngine()
        payload = engine.process_or_passthrough(
            "hagamos yoga",
            {"intent_name": "yoga_request", "response": "x", "confidence": 0.9, "pilar": "emocional"},
        )
        self.assertTrue(engine.is_active)
        self.assertEqual(payload["intent_name"], "yoga_pose")
        self.assertIn("árbol", payload["response"].lower())

    def test_listo_avanza_postura(self) -> None:
        engine = YogaEngine()
        engine.process_or_passthrough("yoga", {"intent_name": "yoga_request", "response": "", "confidence": 1, "pilar": "emocional"})
        second = engine.process_or_passthrough("listo", {"intent_name": "unknown", "response": "", "confidence": 0, "pilar": "general"})
        self.assertTrue(engine.is_active)
        self.assertEqual(second["intent_name"], "yoga_pose")
        self.assertNotIn("árbol", second["response"].lower())

    def test_basta_corta(self) -> None:
        engine = YogaEngine()
        engine.process_or_passthrough("yoga", {"intent_name": "yoga_request", "response": "", "confidence": 1, "pilar": "emocional"})
        end = engine.process_or_passthrough("basta", {"intent_name": "unknown", "response": "", "confidence": 0, "pilar": "general"})
        self.assertFalse(engine.is_active)
        self.assertIn("descans", end["response"].lower())

    def test_completa_todas_las_posturas(self) -> None:
        engine = YogaEngine()
        engine.process_or_passthrough("yoga", {"intent_name": "yoga_request", "response": "", "confidence": 1, "pilar": "emocional"})
        payload = {"intent_name": "unknown", "response": "", "confidence": 0, "pilar": "general"}
        while engine.is_active:
            last = engine.process_or_passthrough("ya", payload)
        self.assertFalse(engine.is_active)
        self.assertIn("muy bien", last["response"].lower())

    def test_sin_yoga_passthrough(self) -> None:
        engine = YogaEngine()
        original = {"intent_name": "greeting", "response": "hola", "confidence": 0.9, "pilar": "vincular"}
        self.assertEqual(engine.process_or_passthrough("hola", original), original)


if __name__ == "__main__":
    unittest.main()
