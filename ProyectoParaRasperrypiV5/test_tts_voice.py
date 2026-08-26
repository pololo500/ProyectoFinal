"""Tests de voz Piper (texto, modelo, parámetros)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workers import SpeechWorker


class TestPrepareTtsText(unittest.TestCase):
    def test_agrega_punto_si_falta(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola"), "hola.")

    def test_no_toca_exclamacion(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("¡Hola!"), "¡Hola!")

    def test_no_toca_pregunta(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("¿Todo bien?"), "¿Todo bien?")

    def test_no_toca_puntos_suspensivos(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola…"), "hola…")

    def test_colapsa_espacios(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text("hola   che"), "hola che.")

    def test_vacio_sigue_vacio(self) -> None:
        self.assertEqual(SpeechWorker._prepare_tts_text(""), "")
        self.assertEqual(SpeechWorker._prepare_tts_text("   "), "")

    def test_speak_encola_texto_preparado(self) -> None:
        worker = SpeechWorker()
        worker.speak("hola")
        self.assertEqual(worker._queue.get_nowait(), "hola.")

    def test_speak_no_encola_si_solo_habia_markup(self) -> None:
        worker = SpeechWorker()
        worker.speak("  [DALE]  ")
        self.assertTrue(worker._queue.empty())


class TestPiperVoiceConfig(unittest.TestCase):
    def test_modelo_es_daniela_ar_high(self) -> None:
        self.assertEqual(SpeechWorker.PIPER_MODEL_NAME, "es_AR-daniela-high")
        self.assertEqual(SpeechWorker.PIPER_MODEL_HF_PATH, "es/es_AR/daniela/high")

    def test_parametros_de_sintesis(self) -> None:
        self.assertAlmostEqual(SpeechWorker.PIPER_LENGTH_SCALE, 1.08)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_SCALE, 0.667)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_W_SCALE, 0.90)

    def test_ensure_piper_model_descarga_daniela_si_falta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            with patch.object(Path, "home", return_value=fake_home), patch(
                "workers.urllib.request.urlretrieve"
            ) as retrieve:
                path = SpeechWorker._ensure_piper_model()
            self.assertEqual(path.name, "es_AR-daniela-high.onnx")
            urls = [call.args[0] for call in retrieve.call_args_list]
            self.assertTrue(
                any("es/es_AR/daniela/high/es_AR-daniela-high.onnx" in u for u in urls)
            )
            self.assertTrue(
                any("es/es_AR/daniela/high/es_AR-daniela-high.onnx.json" in u for u in urls)
            )

    def test_ensure_piper_model_no_redescarga_si_existe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            cache = fake_home / ".edge_ai_models" / "piper"
            cache.mkdir(parents=True)
            (cache / "es_AR-daniela-high.onnx").write_bytes(b"x")
            (cache / "es_AR-daniela-high.onnx.json").write_text("{}")
            with patch.object(Path, "home", return_value=fake_home), patch(
                "workers.urllib.request.urlretrieve"
            ) as retrieve:
                path = SpeechWorker._ensure_piper_model()
            retrieve.assert_not_called()
            self.assertEqual(path, cache / "es_AR-daniela-high.onnx")


if __name__ == "__main__":
    unittest.main()
