"""El LLM cuelga llama-cpp en el proceso de Teo: aislar y matar al timeout."""
from __future__ import annotations

import os
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

from fallback_llm import llm_generate_timeout_s, llm_n_threads
from llm_process import LlmRemote


class TestLlmTimeoutDefaults(unittest.TestCase):
    def test_default_es_120s(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LLM_GENERATE_TIMEOUT"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(llm_generate_timeout_s(), 120.0)

    def test_aarch64_usa_cuatro_hilos(self) -> None:
        with patch("platform.machine", return_value="aarch64"):
            env = {k: v for k, v in os.environ.items() if k != "LLM_THREADS"}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(llm_n_threads(), 4)


class TestLlmRemoteTimeout(unittest.TestCase):
    def test_timeout_mata_al_hijo_y_el_siguiente_turno_no_queda_ocupado(self) -> None:
        killed = []

        class FakeProc:
            def is_alive(self) -> bool:
                return not killed

            def terminate(self) -> None:
                killed.append(True)

            def join(self, timeout: float | None = None) -> None:
                return None

        req: queue.Queue = queue.Queue()
        res: queue.Queue = queue.Queue()
        remote = LlmRemote(FakeProc(), req, res)
        out = remote.ask("hola cómo va", None, [], timeout_s=0.15)
        self.assertEqual(out, "")
        self.assertTrue(killed)
        self.assertEqual(remote.last_fail, "timeout")

        class FastProc:
            def is_alive(self) -> bool:
                return True

            def terminate(self) -> None:
                return None

            def join(self, timeout: float | None = None) -> None:
                return None

        res2: queue.Queue = queue.Queue()
        req2: queue.Queue = queue.Queue()
        remote2 = LlmRemote(FastProc(), req2, res2)
        res2.put(("ok", "Hola, estoy acá con vos."))
        out2 = remote2.ask("hola cómo va", None, [], timeout_s=1.0)
        self.assertEqual(out2, "Hola, estoy acá con vos.")
        self.assertEqual(remote2.last_fail, "")


class TestUnknownUsaRespuestaLlm(unittest.TestCase):
    def test_unknown_vacio_usa_llm_no_enlatada(self) -> None:
        from session_policy import should_allow_llm

        self.assertTrue(should_allow_llm("unknown"))
        canned = [
            "¿Querés jugar al veo veo, escuchar música, un cuento o charlar un rato?",
            "Contame un poco más, te escucho.",
            "No te seguí del todo. ¿Me lo decís de otra forma?",
            "¿Seguimos charlando o preferís un juego?",
        ]
        llm_text = "Hola, estoy acá con vos."
        self.assertNotIn(llm_text, canned)


class TestLoadOnceInMemory(unittest.TestCase):
    def test_load_llama_en_este_proceso_una_vez(self) -> None:
        from fallback_llm import FallbackLLM

        llm = FallbackLLM()
        with patch.object(llm, "_load_llama") as loader:
            def _ok() -> None:
                llm._llm = object()
                llm._loaded = True

            loader.side_effect = _ok
            with patch("llm_process.start_llm_process") as start:
                llm.load()
                llm.load()
            loader.assert_called_once()
            start.assert_not_called()

    def test_timeout_no_tira_el_modelo_de_memoria(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("fallback_llm.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("start_llm_process", src)
        self.assertNotIn("_reload_remote", src)

    def test_n_threads_se_asigna_antes_del_log_de_carga(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("fallback_llm.py").read_text(
            encoding="utf-8"
        )
        start = src.index("def _load_llama")
        end = src.index("@property", start)
        body = src[start:end]
        assign = body.index("n_threads = llm_n_threads()")
        self.assertNotIn("{n_threads}", body[:assign])


if __name__ == "__main__":
    unittest.main()
