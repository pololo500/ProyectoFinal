"""Límites de latencia A: beam Whisper, n_ctx, historial (rollback por env)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from conversation_memory import ConversationMemory
from fallback_llm import llm_n_ctx
from workers import whisper_beam_size

_WORKERS = Path(__file__).resolve().parent / "workers.py"
_FALLBACK = Path(__file__).resolve().parent / "fallback_llm.py"


class TestWhisperBeam(unittest.TestCase):
    def test_default_es_1(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "WHISPER_BEAM"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(whisper_beam_size(), 1)

    def test_rollback_env_5(self) -> None:
        with patch.dict(os.environ, {"WHISPER_BEAM": "5"}):
            self.assertEqual(whisper_beam_size(), 5)

    def test_transcribe_usa_el_helper(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn("beam_size=whisper_beam_size()", src)
        self.assertNotIn("beam_size=5", src)


class TestLlmNCtx(unittest.TestCase):
    def test_default_es_2048(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LLM_N_CTX"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(llm_n_ctx(), 2048)

    def test_env_permite_1024(self) -> None:
        with patch.dict(os.environ, {"LLM_N_CTX": "1024"}):
            self.assertEqual(llm_n_ctx(), 1024)

    def test_llama_usa_el_helper(self) -> None:
        src = _FALLBACK.read_text(encoding="utf-8")
        self.assertIn("n_ctx=llm_n_ctx()", src)
        self.assertNotIn("n_ctx=2048", src)

    def test_workers_no_bloquea_llm_con_vosk(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertNotIn("and not vosk_stt", src)
        self.assertIn("should_allow_llm(", src)

    def test_llm_se_carga_antes_de_escuchar(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertNotIn("cargando LLM de fallback en segundo plano", src)
        load_at = src.find("self.fallback_llm.load()")
        listen_at = src.find("silero-vad: escuchando...")
        self.assertGreater(load_at, 0)
        self.assertGreater(listen_at, load_at)

    def test_mientras_piensa_pone_pensando_en_pantalla(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn('set_expression("pensando")', src)


class TestConvoMaxTurns(unittest.TestCase):
    def test_default_son_4_turnos(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "CONVO_MAX_TURNS"}
        with patch.dict(os.environ, env, clear=True):
            mem = ConversationMemory()
            for i in range(6):
                mem.add_turn(f"u{i}", f"a{i}")
            self.assertEqual(len(mem.messages()), 8)
            self.assertEqual(mem.messages()[0]["content"], "u2")

    def test_rollback_env_10(self) -> None:
        with patch.dict(os.environ, {"CONVO_MAX_TURNS": "10"}):
            mem = ConversationMemory()
            for i in range(12):
                mem.add_turn(f"u{i}", f"a{i}")
            self.assertEqual(len(mem.messages()), 20)
            self.assertEqual(mem.messages()[0]["content"], "u2")


if __name__ == "__main__":
    unittest.main()
