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

    def test_mayusculas_no_deletrea_dia(self) -> None:
        out = SpeechWorker._prepare_tts_text("Dale, te leo EL PRIMER DÍA DE CLASES")
        self.assertNotIn("DÍA", out)
        self.assertIn("día", out)
        self.assertIn("el primer día de clases", out)

    def test_no_baja_una_frase_normal(self) -> None:
        self.assertEqual(
            SpeechWorker._prepare_tts_text("Había una vez un sapo."),
            "Había una vez un sapo.",
        )

    def test_speak_encola_texto_preparado(self) -> None:
        worker = SpeechWorker()
        worker.speak("hola")
        self.assertEqual(worker._queue.get_nowait(), "hola.")
        self.assertTrue(worker.is_busy())

    def test_speak_no_encola_si_solo_habia_markup(self) -> None:
        worker = SpeechWorker()
        worker.speak("  [DALE]  ")
        self.assertTrue(worker._queue.empty())


class TestPiperVoiceConfig(unittest.TestCase):
    def test_modelo_es_daniela_ar_high(self) -> None:
        self.assertEqual(SpeechWorker.PIPER_MODEL_NAME, "es_AR-daniela-high")
        self.assertEqual(SpeechWorker.PIPER_MODEL_HF_PATH, "es/es_AR/daniela/high")

    def test_parametros_de_sintesis(self) -> None:
        self.assertAlmostEqual(SpeechWorker.PIPER_LENGTH_SCALE, 1.20)
        self.assertGreater(SpeechWorker.PIPER_STORY_LENGTH_SCALE, SpeechWorker.PIPER_LENGTH_SCALE)
        self.assertAlmostEqual(SpeechWorker.PIPER_STORY_LENGTH_SCALE, 1.35)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_SCALE, 0.667)
        self.assertAlmostEqual(SpeechWorker.PIPER_NOISE_W_SCALE, 0.98)

    def test_pipeline_del_cuento_usa_ritmo_lento(self) -> None:
        import numpy as np

        worker = SpeechWorker(output_device_index=0)
        worker._piper_voice = object()
        scales: list[float | None] = []

        def synth(text: str, length_scale: float | None = None):
            scales.append(length_scale)
            return (np.zeros(8, dtype=np.float32), 22050)

        with patch.object(worker, "_synthesize_piper_pcm", side_effect=synth), patch.object(
            worker, "_play_wav_via_output_stream"
        ):
            worker._speak_sentence_pipeline(["Uno.", "Dos."])
        self.assertTrue(scales)
        self.assertTrue(all(s == SpeechWorker.PIPER_STORY_LENGTH_SCALE for s in scales))

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
