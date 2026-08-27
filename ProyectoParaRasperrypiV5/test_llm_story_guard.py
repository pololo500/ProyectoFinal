"""El LLM no debe invitar a un cuento si el nene no lo pidió."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fallback_llm import _SYSTEM_PROMPT, drop_unsolicited_story_offer, selected_llm_spec


class TestDropUnsolicitedStory(unittest.TestCase):
    def test_sandwich_no_historia(self) -> None:
        user = "Tengo un poco más alegría. Más lento. Quiero comer un zanguche."
        reply = (
            "Un zanguche, eso suena delicioso. "
            "Dale, pedime una historia corta sobre un zanguche."
        )
        out = drop_unsolicited_story_offer(user, reply)
        self.assertIn("zanguche", out.lower())
        self.assertNotIn("historia", out.lower())
        self.assertNotIn("cuento", out.lower())
        self.assertNotIn("pedime", out.lower())

    def test_si_pidio_cuento_no_se_toca(self) -> None:
        user = "contame un cuento"
        reply = "¡Buenísimo! Decime que te cuente uno."
        self.assertEqual(drop_unsolicited_story_offer(user, reply), reply)

    def test_solo_oferta_queda_frase_neutra(self) -> None:
        out = drop_unsolicited_story_offer(
            "hola",
            "¿Querés que te cuente una historia?",
        )
        self.assertNotIn("historia", out.lower())
        self.assertNotIn("cuento", out.lower())
        self.assertTrue(len(out) > 0)


class TestSystemPromptNoStoryTemplate(unittest.TestCase):
    def test_no_plantilla_pedime_un_cuento(self) -> None:
        self.assertNotIn("pedime un cuento", _SYSTEM_PROMPT.lower())

    def test_prohibits_offering_stories(self) -> None:
        folded = _SYSTEM_PROMPT.lower()
        self.assertTrue(
            "no ofrezcas" in folded or "nunca ofrezcas" in folded,
            _SYSTEM_PROMPT,
        )

    def test_pide_hechos_y_no_inventar(self) -> None:
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("no inventes", folded)
        self.assertIn("no sé", folded)


class TestLlmProfile(unittest.TestCase):
    def test_default_es_8b(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"LLM_PROFILE", "LLM_HF_REPO", "LLM_GGUF"}}
        with patch.dict(os.environ, env, clear=True):
            _repo, filename = selected_llm_spec()
        self.assertIn("8B", filename)

    def test_rollback_3b(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROFILE": "3b", "LLM_HF_REPO": "", "LLM_GGUF": ""},
        ):
            _repo, filename = selected_llm_spec()
        self.assertIn("Llama-3.2-3B", filename)


if __name__ == "__main__":
    unittest.main()
