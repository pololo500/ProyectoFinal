"""Mute de intents cuando el LLM espera respuesta del nene."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from session_policy import (
    MUTE_FAILSAFE_TURNS,
    IntentMute,
    apply_llm_intent_actions,
    game_keyword_while_muted,
    should_run_intent_dispatcher,
)


class TestDispatchHelpers(unittest.TestCase):
    def test_dispatcher_apagado_si_mute(self) -> None:
        self.assertFalse(should_run_intent_dispatcher(True))
        self.assertTrue(should_run_intent_dispatcher(False))

    def test_solo_juegos_de_motor_mientras_mute(self) -> None:
        self.assertEqual(
            game_keyword_while_muted(True, "play_veo_veo"),
            "play_veo_veo",
        )
        self.assertEqual(
            game_keyword_while_muted(True, "play_piedra_papel"),
            "play_piedra_papel",
        )
        self.assertIsNone(game_keyword_while_muted(True, "emotion_angry"))
        self.assertIsNone(game_keyword_while_muted(True, "call_parent"))
        self.assertIsNone(game_keyword_while_muted(False, "play_veo_veo"))
        self.assertIsNone(game_keyword_while_muted(True, None))


class TestIntentMute(unittest.TestCase):
    def test_game_keyword_prende(self) -> None:
        mute = IntentMute(log_fn=lambda *_a, **_k: None)
        mute.apply_tag(on=False, reason="llm_tag", child_text="de que color")
        self.assertTrue(mute.is_muted)
        mute.note_game_keyword("juguemos veo veo")
        self.assertFalse(mute.is_muted)
        self.assertEqual(mute.turns_while_muted, 0)

    def test_ppt_tambien_prende(self) -> None:
        mute = IntentMute(log_fn=lambda *_a, **_k: None)
        mute.apply_tag(on=False, reason="llm_tag")
        mute.note_game_keyword("piedra papel o tijera")
        self.assertFalse(mute.is_muted)

    def test_log_solo_si_cambia(self) -> None:
        logs: list[tuple[str, str]] = []

        def capture(component: str, message: str, elapsed_ms: float | None = None) -> None:
            logs.append((component, message))

        mute = IntentMute(log_fn=capture)
        self.assertTrue(mute.apply_tag(on=False, reason="llm_tag", child_text="color?"))
        self.assertFalse(mute.apply_tag(on=False, reason="llm_tag", child_text="otra"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0][0], "INTENTS")
        self.assertIn("on→off", logs[0][1])
        self.assertIn("reason=llm_tag", logs[0][1])
        self.assertIn("color?", logs[0][1])

    def test_failsafe_a_tres_turnos(self) -> None:
        logs: list[str] = []
        mute = IntentMute(log_fn=lambda _c, msg, **_k: logs.append(msg))
        mute.apply_tag(on=False, reason="llm_tag")
        mute.note_child_turn_still_muted("si")
        self.assertTrue(mute.is_muted)
        mute.note_child_turn_still_muted("rojo")
        self.assertTrue(mute.is_muted)
        mute.note_child_turn_still_muted("el perro")
        self.assertFalse(mute.is_muted)
        self.assertEqual(MUTE_FAILSAFE_TURNS, 3)
        self.assertTrue(any("reason=failsafe" in item for item in logs))

    def test_ultimo_tag_gana_y_notify_fuerza_on(self) -> None:
        mute = IntentMute(log_fn=lambda *_a, **_k: None)
        apply_llm_intent_actions(
            mute,
            [
                {"action": "INTENTS_ON", "param": ""},
                {"action": "INTENTS_OFF", "param": ""},
            ],
            "hola",
        )
        self.assertTrue(mute.is_muted)
        apply_llm_intent_actions(
            mute,
            [
                {"action": "INTENTS_OFF", "param": ""},
                {"action": "NOTIFY_PARENT", "param": "mama"},
            ],
            "llama a mama",
        )
        self.assertFalse(mute.is_muted)


class TestCannedPlayCopy(unittest.TestCase):
    def test_no_inventa_juegos(self) -> None:
        path = Path(__file__).resolve().parent / "intent_rules.json"
        rules = json.loads(path.read_text(encoding="utf-8"))
        for intent_name in ("play_generic", "activity_offer"):
            blob = " ".join(str(item) for item in rules[intent_name]["response"]).lower()
            self.assertNotIn("inventamos", blob, intent_name)
            self.assertNotIn("inventar un juego", blob, intent_name)


class TestActionTagRegex(unittest.TestCase):
    def test_regex_reconoce_intents_on_off(self) -> None:
        from workers import AudioWorker

        names = [m.group(1).upper() for m in AudioWorker._ACTION_TAG_RE.finditer(
            "ok [INTENTS_OFF] chau [INTENTS_ON]"
        )]
        self.assertEqual(names, ["INTENTS_OFF", "INTENTS_ON"])


if __name__ == "__main__":
    unittest.main()
