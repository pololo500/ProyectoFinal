"""El LLM no debe invitar a un cuento si el nene no lo pidió."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fallback_llm import (
    _SYSTEM_PROMPT,
    drop_prompt_leak,
    drop_unsolicited_story_offer,
    selected_llm_spec,
)


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

    def test_prompt_entra_en_n_ctx_1024(self) -> None:
        self.assertLessEqual(len(_SYSTEM_PROMPT), 1800)

    def test_pide_hechos_y_no_inventar(self) -> None:
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("no inventes", folded)
        self.assertIn("no sé", folded)

    def test_intents_on_off_y_juegos_reales(self) -> None:
        self.assertIn("[INTENTS_OFF]", _SYSTEM_PROMPT)
        self.assertIn("[INTENTS_ON]", _SYSTEM_PROMPT)
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("veo veo", folded)
        self.assertIn("piedra", folded)
        self.assertIn("intents_on", folded)

    def test_notify_solo_pedido_o_crisis(self) -> None:
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("[notify_parent", folded)
        self.assertIn("palabra suelta", folded)
        self.assertTrue(
            "no avises" in folded or "no uses [notify_parent]" in folded,
            _SYSTEM_PROMPT,
        )

    def test_prompt_teo_ppt_notify_calm(self) -> None:
        self.assertIn("Piedra Papel o Tijera", _SYSTEM_PROMPT)
        self.assertNotIn("al PPT.", _SYSTEM_PROMPT)
        folded = _SYSTEM_PROMPT.lower()
        self.assertIn("explicandole al padre", folded)
        self.assertIn("despide", folded)


class TestPromptNoCannedEcho(unittest.TestCase):
    """El 3B copia frases del system prompt (VEO VEO / Me llamo TEO / Neutral)."""

    def test_prompt_no_deja_frases_para_copiar(self) -> None:
        self.assertNotIn("Me llamo TEO", _SYSTEM_PROMPT)
        self.assertNotIn("VEO VEO", _SYSTEM_PROMPT)
        folded = _SYSTEM_PROMPT.lower()
        self.assertNotIn("|neutral]", folded)
        self.assertNotIn("feliz|triste", folded)

    def test_alarma_no_es_veo_veo(self) -> None:
        out = drop_prompt_leak("Tengo una alarma.", "VEO VEO.")
        self.assertNotIn("veo", out.lower())
        self.assertGreater(len(out.split()), 2)

    def test_pantalon_no_es_me_llamo_teo(self) -> None:
        out = drop_prompt_leak("Tengo un niña del pantalón.", "Me llamo TEO.")
        self.assertNotIn("me llamo", out.lower())

    def test_si_preguntan_el_nombre_se_deja(self) -> None:
        out = drop_prompt_leak("¿Cómo te llamás?", "Me llamo TEO.")
        self.assertIn("teo", out.lower())

    def test_neutral_suelto_no_se_dice(self) -> None:
        out = drop_prompt_leak("Se volvió imbécil. Qué bueno.", "Neutral.")
        self.assertNotEqual(out.strip().lower().rstrip("."), "neutral")
        self.assertGreater(len(out.split()), 2)


class TestLlmProfile(unittest.TestCase):
    def test_default_es_3b(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in {"LLM_PROFILE", "LLM_HF_REPO", "LLM_GGUF"}}
        with patch.dict(os.environ, env, clear=True):
            _repo, filename = selected_llm_spec()
        self.assertIn("Llama-3.2-3B", filename)

    def test_perfil_1b(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROFILE": "1b", "LLM_HF_REPO": "", "LLM_GGUF": ""},
        ):
            _repo, filename = selected_llm_spec()
        self.assertIn("Llama-3.2-1B", filename)

    def test_rollback_8b(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROFILE": "8b", "LLM_HF_REPO": "", "LLM_GGUF": ""},
        ):
            _repo, filename = selected_llm_spec()
        self.assertIn("8B", filename)


class TestLlmGenerateTimeout(unittest.TestCase):
    def test_si_el_modelo_no_contesta_devuelve_vacio(self) -> None:
        import time

        from fallback_llm import FallbackLLM

        llm = FallbackLLM()
        llm._loaded = True

        class Slow:
            def create_chat_completion(self, **kwargs):  # noqa: ANN003
                time.sleep(4)
                return {"choices": [{"message": {"content": "hola"}}]}

        llm._llm = Slow()
        with patch.dict(os.environ, {"LLM_GENERATE_TIMEOUT": "0.3"}):
            started = time.monotonic()
            out = llm.generate("hola")
        self.assertEqual(out, "")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_aarch64_usa_cuatro_hilos(self) -> None:
        from fallback_llm import llm_n_threads

        with patch("platform.machine", return_value="aarch64"):
            with patch.dict(os.environ, {"LLM_THREADS": ""}):
                self.assertEqual(llm_n_threads(), 4)


if __name__ == "__main__":
    unittest.main()

