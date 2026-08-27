"""Tests de corrección y filtro STT."""
from __future__ import annotations

import unittest

from stt_correct import correct_stt_text, polish_stt_text


_KNOWN = {
    "para",
    "un",
    "chaval",
    "son",
    "oh",
    "quiero",
    "jugar",
    "piedra",
    "papel",
    "tijera",
    "cuento",
    "no",
    "me",
    "parece",
    "que",
    "voy",
    "a",
    "eh",
    "es",
    "la",
    "capital",
    "de",
    "dinamarca",
    "cuanto",
    "tarea",
    "matematica",
    "hola",
    "comer",
    "sandwich",
    "bueno",
    "si",
    "o",
}


def _known_spanish(word: str) -> bool:
    folded = word.lower()
    folded = (
        folded.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )
    return folded in _KNOWN


class TestCorrectStt(unittest.TestCase):
    def test_tiguera_es_tijera(self) -> None:
        self.assertEqual(
            correct_stt_text("¡Tiguera!", extra_words=("piedra", "papel", "tijera")),
            "¡tijera!",
        )

    def test_piera_es_piedra(self) -> None:
        self.assertIn(
            "piedra",
            correct_stt_text("¡Piera!", extra_words=("piedra", "papel", "tijera")).lower(),
        )

    def test_tapel_es_papel(self) -> None:
        self.assertIn(
            "papel",
            correct_stt_text("¡Tapel?", extra_words=("piedra", "papel", "tijera")).lower(),
        )

    def test_pega_papelotijera(self) -> None:
        out = correct_stt_text("Juguemos al Piedra Papelotijera.")
        self.assertIn("papel o tijera", out.lower())
        self.assertNotIn("papelotijera", out.lower())

    def test_no_toca_frase_normal(self) -> None:
        frase = "Quiero comer un sandwich."
        self.assertEqual(correct_stt_text(frase), frase)

    def test_hola_queda(self) -> None:
        self.assertEqual(correct_stt_text("Hola."), "Hola.")

    def test_para_no_se_vuelve_papa(self) -> None:
        out = correct_stt_text("Para un chaval.")
        self.assertIn("Para", out)
        self.assertNotIn("papa", out.lower())

    def test_cuanto_no_se_vuelve_cuento(self) -> None:
        out = correct_stt_text("¿Cuánto es 4 más 8?")
        self.assertNotIn("cuento", out.lower())
        self.assertIn("cuánto", out.lower())


class TestFilterStt(unittest.TestCase):
    def test_saca_ingles_plunder(self) -> None:
        out = polish_stt_text(
            "Bueno, sí, me parece que me voy a plunder, eh?",
            is_known_spanish=_known_spanish,
        )
        self.assertNotIn("plunder", out.lower())
        self.assertIn("parece", out.lower())

    def test_saca_pancake(self) -> None:
        out = polish_stt_text("Es un pancake, no?", is_known_spanish=_known_spanish)
        self.assertNotIn("pancake", out.lower())
        self.assertIn("es un", out.lower())

    def test_saca_inventadas(self) -> None:
        out = polish_stt_text(
            "Para un chaval. Son paladitos. Oh, goch!",
            is_known_spanish=_known_spanish,
        )
        self.assertNotIn("paladitos", out.lower())
        self.assertNotIn("goch", out.lower())
        self.assertIn("chaval", out.lower())

    def test_mantiene_espanol_normal(self) -> None:
        frase = "Quiero jugar a piedra, papel o tijera."
        self.assertEqual(
            polish_stt_text(frase, is_known_spanish=_known_spanish).lower(),
            frase.lower(),
        )

    def test_mantiene_nombre_con_acento(self) -> None:
        out = polish_stt_text("Me llamo Tomás.", is_known_spanish=_known_spanish)
        self.assertIn("tomás", out.lower())


if __name__ == "__main__":
    unittest.main()
