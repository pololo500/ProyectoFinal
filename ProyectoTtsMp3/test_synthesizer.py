"""Tests de texto y de Elena Neural (edge-tts)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synthesizer import (
    VOICE_NAME,
    VOICE_RATE,
    generate_mp3,
    prepare_tts_text,
    suggested_mp3_name,
)


class FakeCommunicate:
    last: FakeCommunicate | None = None

    def __init__(
        self,
        text: str,
        voice: str,
        *,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> None:
        self.text = text
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch
        type(self).last = self

    async def save(self, path: str) -> None:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xff\xf3fake-mp3")


class TestPrepareTtsText(unittest.TestCase):
    def test_agrega_punto_si_falta(self) -> None:
        self.assertEqual(prepare_tts_text("hola"), "hola.")

    def test_no_toca_exclamacion(self) -> None:
        self.assertEqual(prepare_tts_text("¡Hola!"), "¡Hola!")

    def test_no_toca_pregunta(self) -> None:
        self.assertEqual(prepare_tts_text("¿Todo bien?"), "¿Todo bien?")

    def test_no_toca_puntos_suspensivos(self) -> None:
        self.assertEqual(prepare_tts_text("hola…"), "hola…")

    def test_colapsa_espacios(self) -> None:
        self.assertEqual(prepare_tts_text("hola   che"), "hola che.")

    def test_vacio_sigue_vacio(self) -> None:
        self.assertEqual(prepare_tts_text(""), "")
        self.assertEqual(prepare_tts_text("   "), "")


class TestSuggestedMp3Name(unittest.TestCase):
    def test_usa_texto_y_extension_mp3(self) -> None:
        self.assertEqual(suggested_mp3_name("hola"), "hola.mp3")

    def test_vacio_usa_nombre_por_defecto(self) -> None:
        self.assertEqual(suggested_mp3_name("  "), "teo.mp3")

    def test_saca_caracteres_invalidos_en_windows(self) -> None:
        self.assertEqual(suggested_mp3_name("hola: teo?"), "hola teo.mp3")


class TestElenaVoiceConfig(unittest.TestCase):
    def test_voz_es_elena_argentina(self) -> None:
        self.assertEqual(VOICE_NAME, "es-AR-ElenaNeural")

    def test_ritmo_un_poco_pausado(self) -> None:
        self.assertEqual(VOICE_RATE, "-8%")


class TestGenerateMp3(unittest.TestCase):
    def setUp(self) -> None:
        FakeCommunicate.last = None

    def test_rechaza_texto_vacio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "teo.mp3"
            with self.assertRaises(ValueError):
                generate_mp3("  ", dest, communicate_factory=FakeCommunicate)
            self.assertIsNone(FakeCommunicate.last)

    def test_usa_elena_texto_preparado_y_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.mp3"
            result = generate_mp3(
                "hola", dest, communicate_factory=FakeCommunicate
            )
            self.assertEqual(result, dest)
            self.assertTrue(dest.is_file())
            self.assertGreater(dest.stat().st_size, 0)
            call = FakeCommunicate.last
            assert call is not None
            self.assertEqual(call.text, "hola.")
            self.assertEqual(call.voice, VOICE_NAME)
            self.assertEqual(call.rate, VOICE_RATE)

    def test_crea_carpeta_destino(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "sub" / "out.mp3"
            generate_mp3("hola", dest, communicate_factory=FakeCommunicate)
            self.assertTrue(dest.is_file())


if __name__ == "__main__":
    unittest.main()
