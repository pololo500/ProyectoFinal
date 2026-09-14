"""Tests TDD del estado prendido/apagado (sueño) de Teo."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import unittest

from sleep_state import (
    NOT_READY_CLIP_NAME,
    SLEEP_CONFIRM_PHRASE,
    SLEEP_GOODNIGHT_PHRASE,
    SleepState,
    child_sleep_decision,
    is_sleep_confirm_yes,
    is_sleep_request_text,
    not_ready_clip_path,
)


class TestSleepPhrases(unittest.TestCase):
    def test_confirm_copy(self) -> None:
        self.assertIn("dormir", SLEEP_CONFIRM_PHRASE.lower())
        self.assertIn("bueno", SLEEP_GOODNIGHT_PHRASE.lower())

    def test_si_claro(self) -> None:
        for phrase in ("sí", "si", "dale", "bueno", "ok", "sí quiero", "sí teo"):
            self.assertTrue(is_sleep_confirm_yes(phrase), phrase)

    def test_no_es_si_claro(self) -> None:
        self.assertFalse(is_sleep_confirm_yes("juguemos"))
        self.assertFalse(is_sleep_confirm_yes("sí pero seguí"))
        self.assertFalse(is_sleep_confirm_yes(""))
        self.assertFalse(is_sleep_confirm_yes("chau"))

    def test_pedido_de_irsr(self) -> None:
        self.assertTrue(is_sleep_request_text("chau"))
        self.assertTrue(is_sleep_request_text("Chau Teo!"))
        self.assertTrue(is_sleep_request_text("no quiero jugar"))
        self.assertTrue(is_sleep_request_text("no quiero jugar más"))
        self.assertTrue(is_sleep_request_text("no quiero más"))
        self.assertFalse(is_sleep_request_text("hola"))
        self.assertFalse(is_sleep_request_text("juguemos veo veo"))

    def test_pedido_oral_real_del_stt(self) -> None:
        """Frases que Whisper mandó al servidor de PC el 2026-09-13."""
        for phrase in (
            "Chao, apágate.",
            "Teo, apagate.",
            "Teo, apágate.",
            "Sí, apágate.",
            "chao",
            "apagate",
            "vete a dormir",
        ):
            self.assertTrue(is_sleep_request_text(phrase), phrase)
        self.assertFalse(is_sleep_request_text("me voy a jugar"))
        self.assertFalse(is_sleep_request_text("apaga la música"))

    def test_si_con_apagate_es_confirmacion(self) -> None:
        self.assertTrue(is_sleep_confirm_yes("Sí, apágate."))
        self.assertTrue(is_sleep_confirm_yes("dale apagate"))
        self.assertFalse(is_sleep_confirm_yes("apagate"))

    def test_decision_oral_duerme_o_pregunta(self) -> None:
        self.assertEqual(child_sleep_decision("Chao, apágate.", awaiting=False), "ask")
        self.assertEqual(child_sleep_decision("Sí, apágate.", awaiting=False), "sleep")
        self.assertEqual(child_sleep_decision("sí", awaiting=True), "sleep")
        self.assertEqual(child_sleep_decision("apagate", awaiting=True), "sleep")
        self.assertEqual(child_sleep_decision("juguemos", awaiting=True), "continue")
        self.assertEqual(child_sleep_decision("hola", awaiting=False), "continue")


class TestSleepStateMachine(unittest.TestCase):
    def test_boot_es_loading(self) -> None:
        state = SleepState()
        self.assertEqual(state.phase(), "loading")
        self.assertFalse(state.power_on)
        self.assertFalse(state.models_ready)
        self.assertFalse(state.status_power_on())

    def test_modelos_sin_cola_queda_dormido(self) -> None:
        state = SleepState()
        woke = state.mark_models_ready()
        self.assertFalse(woke)
        self.assertEqual(state.phase(), "asleep")
        self.assertFalse(state.status_power_on())

    def test_wake_app_durante_carga_encola_y_prende_al_listo(self) -> None:
        state = SleepState()
        result = state.request_wake("app")
        self.assertEqual(result, "queued")
        self.assertTrue(state.status_power_on())
        self.assertEqual(state.phase(), "loading")
        woke = state.mark_models_ready()
        self.assertTrue(woke)
        self.assertEqual(state.phase(), "awake")
        self.assertTrue(state.status_power_on())

    def test_panza_despierto_es_abrazo(self) -> None:
        state = SleepState()
        state.mark_models_ready()
        state.request_wake("app")
        self.assertEqual(state.on_belly(), "hug")
        self.assertEqual(state.phase(), "awake")

    def test_panza_dormido_prende(self) -> None:
        state = SleepState()
        state.mark_models_ready()
        self.assertEqual(state.on_belly(), "wake")
        self.assertEqual(state.phase(), "awake")

    def test_panza_cargando_encola(self) -> None:
        state = SleepState()
        self.assertEqual(state.on_belly(), "queue")
        self.assertTrue(state.pending_wake)
        state.mark_models_ready()
        self.assertEqual(state.phase(), "awake")

    def test_chip_off_ignora_panza(self) -> None:
        state = SleepState()
        state.mark_models_ready()
        state.set_belly_wake_enabled(False)
        self.assertEqual(state.on_belly(), "ignore")
        self.assertEqual(state.phase(), "asleep")
        self.assertEqual(state.on_belly(), "ignore")

    def test_chip_off_en_carga_no_encola(self) -> None:
        state = SleepState()
        state.set_belly_wake_enabled(False)
        self.assertEqual(state.on_belly(), "ignore")
        self.assertFalse(state.pending_wake)

    def test_tope_bloquea_panza_ese_dia(self) -> None:
        today = date(2026, 9, 13)
        state = SleepState()
        state.mark_models_ready()
        state.request_wake("app", today=today)
        state.request_sleep("playtime", today=today)
        self.assertEqual(state.phase(), "asleep")
        self.assertEqual(state.on_belly(today=today), "ignore")
        manana = today + timedelta(days=1)
        self.assertEqual(state.on_belly(today=manana), "wake")

    def test_wake_padre_limpia_bloqueo_panza(self) -> None:
        today = date(2026, 9, 13)
        state = SleepState()
        state.mark_models_ready()
        state.request_wake("app", today=today)
        state.request_sleep("playtime", today=today)
        state.note_parent_wake()
        result = state.request_wake("app", today=today)
        self.assertEqual(result, "woke")
        self.assertEqual(state.on_belly(today=today), "hug")

    def test_app_apaga_inmediato(self) -> None:
        state = SleepState()
        state.mark_models_ready()
        state.request_wake("app")
        state.request_sleep("app")
        self.assertEqual(state.phase(), "asleep")
        self.assertFalse(state.awaiting_sleep_confirm)

    def test_clip_path(self) -> None:
        path = not_ready_clip_path(Path("/tmp/teo"))
        self.assertEqual(path.name, NOT_READY_CLIP_NAME)
        self.assertEqual(path.parent.name, "assets")


if __name__ == "__main__":
    unittest.main()
