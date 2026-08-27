"""Tests TDD de políticas de sesión (volumen, noche, playtime, privacidad, barge-in)."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
import tempfile

import numpy as np

from session_policy import (
    PlaytimeGuard,
    apply_gain,
    effective_volume_limit,
    gain_from_limit,
    is_barge_in_text,
    is_clear_keyword_intent,
    mic_open_for_listen,
    night_should_engage,
    sanitize_notification_extra,
    telemetry_range_summary,
)


class TestVolumeGain(unittest.TestCase):
    def test_cien_no_atenuar(self) -> None:
        self.assertAlmostEqual(gain_from_limit(100), 1.0)

    def test_cincuenta_mitad(self) -> None:
        self.assertAlmostEqual(gain_from_limit(50), 0.5)

    def test_cero_silencio(self) -> None:
        self.assertAlmostEqual(gain_from_limit(0), 0.0)

    def test_clamp(self) -> None:
        self.assertAlmostEqual(gain_from_limit(200), 1.0)
        self.assertAlmostEqual(gain_from_limit(-10), 0.0)

    def test_apply_gain_escala_pico(self) -> None:
        audio = np.array([0.5, -0.5], dtype=np.float32)
        out = apply_gain(audio, 0.5)
        self.assertAlmostEqual(float(out.max()), 0.25, places=5)

    def test_noche_baja_el_tope(self) -> None:
        self.assertEqual(effective_volume_limit(100, night_mode=True), 40)
        self.assertEqual(effective_volume_limit(20, night_mode=True), 20)
        self.assertEqual(effective_volume_limit(100, night_mode=False), 100)


class TestNightMode(unittest.TestCase):
    def test_juegos_bloqueados(self) -> None:
        self.assertFalse(night_should_engage("play_veo_veo"))
        self.assertFalse(night_should_engage("play_piedra_papel"))
        self.assertFalse(night_should_engage("story_request"))
        self.assertFalse(night_should_engage("song_request"))
        self.assertFalse(night_should_engage("yoga_request"))

    def test_crisis_y_padres_permitidos(self) -> None:
        self.assertTrue(night_should_engage("call_parent"))
        self.assertTrue(night_should_engage("crisis_cry"))
        self.assertTrue(night_should_engage("tired_sleepy"))
        self.assertTrue(night_should_engage("hug_request"))

    def test_sin_noche_todo_pasa(self) -> None:
        self.assertTrue(night_should_engage("play_veo_veo", night_mode=False))


class TestPlaytimeGuard(unittest.TestCase):
    def test_cero_es_sin_limite(self) -> None:
        guard = PlaytimeGuard(limit_minutes=0)
        guard.add_seconds(10_000)
        self.assertFalse(guard.is_over_limit())

    def test_corta_al_exceder(self) -> None:
        guard = PlaytimeGuard(limit_minutes=1, today=date(2026, 8, 26))
        guard.add_seconds(59)
        self.assertFalse(guard.is_over_limit())
        guard.add_seconds(2)
        self.assertTrue(guard.is_over_limit())

    def test_crisis_sigue_permitida(self) -> None:
        guard = PlaytimeGuard(limit_minutes=1)
        guard.add_seconds(120)
        self.assertTrue(guard.allows_intent("call_parent"))
        self.assertFalse(guard.allows_intent("play_veo_veo"))


class TestPrivacyExtra(unittest.TestCase):
    def test_saca_texto_del_nene(self) -> None:
        extra = sanitize_notification_extra({"intent": "call_parent", "text": "quiero a mama"})
        self.assertIsNotNone(extra)
        self.assertNotIn("text", extra)
        self.assertEqual(extra["intent"], "call_parent")

    def test_saca_utterance_y_respuesta(self) -> None:
        extra = sanitize_notification_extra(
            {"intent": "crisis_cry", "utterance": "aaa", "response_given": "hola"}
        )
        self.assertIsNotNone(extra)
        self.assertNotIn("utterance", extra)
        self.assertNotIn("response_given", extra)

    def test_none_sigue_none(self) -> None:
        self.assertIsNone(sanitize_notification_extra(None))


class TestBargeIn(unittest.TestCase):
    def test_detecta_corte(self) -> None:
        self.assertTrue(is_barge_in_text("basta"))
        self.assertTrue(is_barge_in_text("para la musica"))
        self.assertTrue(is_barge_in_text("quiero a mama"))
        self.assertFalse(is_barge_in_text("quiero jugar"))


class TestMicHalfDuplex(unittest.TestCase):
    def test_cerrado_si_esta_hablando(self) -> None:
        self.assertFalse(mic_open_for_listen(True, now=10.0, echo_mute_until=0.0))

    def test_abierto_si_idle(self) -> None:
        self.assertTrue(mic_open_for_listen(False, now=10.0, echo_mute_until=0.0))

    def test_cerrado_en_cola_de_eco(self) -> None:
        self.assertFalse(mic_open_for_listen(False, now=10.0, echo_mute_until=10.3))

    def test_abre_despues_de_la_cola(self) -> None:
        self.assertTrue(mic_open_for_listen(False, now=10.5, echo_mute_until=10.3))

    def test_keywords_claros(self) -> None:
        self.assertEqual(is_clear_keyword_intent("dame un abrazo"), "hug_request")
        self.assertEqual(is_clear_keyword_intent("hagamos yoga"), "yoga_request")
        self.assertEqual(is_clear_keyword_intent("llama a mama"), "call_parent")
        self.assertEqual(is_clear_keyword_intent("como te llamas"), "identity_name")
        self.assertNotEqual(is_clear_keyword_intent("como te llamas"), "call_parent")
        self.assertIsNone(is_clear_keyword_intent("quiero a mama"))
        self.assertEqual(is_clear_keyword_intent("piedra papel o tijera"), "play_piedra_papel")
        self.assertEqual(
            is_clear_keyword_intent("Tengo un poco más alegría. Quiero comer un zanguche."),
            "needs_basic",
        )


class TestTelemetryRange(unittest.TestCase):
    def test_suma_varios_dias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = date(2026, 8, 1)
            d2 = date(2026, 8, 2)
            for day, n in ((d1, 3), (d2, 5)):
                payload = {
                    "date": day.isoformat(),
                    "summary": {
                        "total_interactions": n,
                        "total_duration_s": n * 10.0,
                        "pillar_counts": {"cognitivo": n},
                        "crisis_count": 0,
                        "games_played": 1,
                        "routines_completed": 0,
                        "new_words_today": 1,
                    },
                    "events": [],
                }
                (root / f"telemetry_{day.isoformat()}.json").write_text(
                    __import__("json").dumps(payload), encoding="utf-8"
                )
            summary = telemetry_range_summary(root, d1, d2)
            self.assertEqual(summary["total_interactions"], 8)
            self.assertEqual(summary["pillar_counts"]["cognitivo"], 8)
            self.assertEqual(summary["days"], 2)
            self.assertEqual(len(summary["daily"]), 2)
            self.assertEqual(summary["daily"][0]["interactions"], 3)
            self.assertEqual(summary["daily"][1]["interactions"], 5)


if __name__ == "__main__":
    unittest.main()
