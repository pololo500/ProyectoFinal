"""Cada clip de STT se guarda en audios/ con el nombre de la transcripción."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from debug_logger import filename_from_transcript, save_named_transcript_wav


class TestFilenameFromTranscript(unittest.TestCase):
    def test_hola_soy_carlos(self) -> None:
        self.assertEqual(
            filename_from_transcript("Hola, soy carlos"),
            "hola soy carlos",
        )

    def test_vacio_es_sin_texto(self) -> None:
        self.assertEqual(filename_from_transcript(""), "sin_texto")
        self.assertEqual(filename_from_transcript("   ???  "), "sin_texto")

    def test_saca_caracteres_de_path(self) -> None:
        name = filename_from_transcript('hola/soy:carlos*?')
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)
        self.assertNotIn("*", name)
        self.assertNotIn("?", name)


class TestSaveNamedTranscriptWav(unittest.TestCase):
    def test_guarda_wav_con_el_texto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = np.zeros(1600, dtype=np.float32)
            path = save_named_transcript_wav(
                audio,
                "Hola, soy carlos",
                sample_rate=16000,
                audio_dir=Path(tmp),
            )
            self.assertIsNotNone(path)
            self.assertEqual(path.name, "hola soy carlos.wav")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 44)

    def test_colision_agrega_sufijo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = np.zeros(800, dtype=np.float32)
            first = save_named_transcript_wav(
                audio, "hola", sample_rate=16000, audio_dir=Path(tmp)
            )
            second = save_named_transcript_wav(
                audio, "hola", sample_rate=16000, audio_dir=Path(tmp)
            )
            self.assertEqual(first.name, "hola.wav")
            self.assertEqual(second.name, "hola_2.wav")


class TestWorkersGuardaElClip(unittest.TestCase):
    def test_transcribe_llama_al_guardado(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("save_named_transcript_wav(", src)


if __name__ == "__main__":
    unittest.main()
