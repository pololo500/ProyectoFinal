"""Dispatcher: solo keywords; el resto unknown (sin MiniLM)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import IntentDispatcher

_RULES = Path(__file__).resolve().parent / "intent_rules.json"


def _dispatcher() -> IntentDispatcher:
    data = json.loads(_RULES.read_text(encoding="utf-8"))
    d = IntentDispatcher.__new__(IntentDispatcher)
    d.intents = data
    d.nlp = None
    d._sentence_model = None
    d._example_docs = {}
    d._example_embeddings = {}
    d._last_canned = {}
    d.current_emotion = None
    return d


class TestKeywordOrUnknown(unittest.TestCase):
    def setUp(self) -> None:
        self.d = _dispatcher()

    def test_zanahoria_unknown(self) -> None:
        self.assertEqual(self.d.dispatch("Zanahoria.")["intent_name"], "unknown")

    def test_bichito_unknown(self) -> None:
        self.assertEqual(
            self.d.dispatch("Encontré un bichito en el jardín.")["intent_name"],
            "unknown",
        )

    def test_hola_greeting(self) -> None:
        out = self.d.dispatch("hola")
        self.assertEqual(out["intent_name"], "greeting")
        self.assertGreaterEqual(out["confidence"], 0.92)
        self.assertTrue(str(out.get("response") or "").strip())

    def test_chau_farewell(self) -> None:
        self.assertEqual(self.d.dispatch("chau")["intent_name"], "farewell")

    def test_hola_me_llamo_unknown(self) -> None:
        self.assertEqual(
            self.d.dispatch("hola me llamo tomas")["intent_name"],
            "unknown",
        )

    def test_me_duele_unknown(self) -> None:
        self.assertEqual(self.d.dispatch("me duele la panza")["intent_name"], "unknown")

    def test_quiero_a_mama_unknown(self) -> None:
        out = self.d.dispatch("quiero a mama")
        self.assertEqual(out["intent_name"], "unknown")

    def test_llama_a_mama_call_parent(self) -> None:
        out = self.d.dispatch("llama a mama")
        self.assertEqual(out["intent_name"], "call_parent")
        self.assertGreaterEqual(out["confidence"], 0.92)
        self.assertTrue(str(out.get("response") or "").strip())

    def test_hablar_con_papa_call_parent(self) -> None:
        self.assertEqual(
            self.d.dispatch("quiero hablar con papa")["intent_name"],
            "call_parent",
        )

    def test_como_te_llamas_no_es_call_parent(self) -> None:
        out = self.d.dispatch("como te llamas")
        self.assertEqual(out["intent_name"], "identity_name")
        self.assertNotEqual(out["intent_name"], "call_parent")

    def test_veo_veo_skill(self) -> None:
        self.assertEqual(
            self.d.dispatch("juguemos veo veo")["intent_name"],
            "play_veo_veo",
        )


class TestNoMinilmLoad(unittest.TestCase):
    def test_from_file_no_carga_minilm(self) -> None:
        d = IntentDispatcher.from_file(_RULES)
        self.assertIsNone(d._sentence_model)

    def test_load_sentence_model_nunca_instancia(self) -> None:
        d = IntentDispatcher.__new__(IntentDispatcher)
        fake = MagicMock()
        fake.SentenceTransformer.return_value = object()
        with patch.dict(sys.modules, {"sentence_transformers": fake}):
            result = IntentDispatcher._load_sentence_model(d)
        self.assertIsNone(result)
        fake.SentenceTransformer.assert_not_called()

    def test_dispatch_no_puntua_embeddings(self) -> None:
        d = _dispatcher()

        def boom(_text: str):
            raise AssertionError("no _score_intents")

        d._score_intents = boom  # type: ignore[method-assign]
        self.assertEqual(d.dispatch("Zanahoria.")["intent_name"], "unknown")
        self.assertEqual(d.dispatch("hola me llamo tomas")["intent_name"], "unknown")


if __name__ == "__main__":
    unittest.main()
