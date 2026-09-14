"""Tests TDD de RobotState: power default off, cola, chip persistido."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from api_server import RobotState
from session_policy import PlaytimeGuard


class TestRobotStatePower(unittest.TestCase):
    def _fresh(self, tmp: str) -> RobotState:
        return RobotState(prefs_path=Path(tmp) / "parental_prefs.json")

    def test_default_apagado_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._fresh(tmp)
            self.assertEqual(rs.sleep.phase(), "loading")
            data = rs.to_dict()
            self.assertFalse(data["power_on"])
            self.assertFalse(data["models_ready"])
            self.assertFalse(data["pending_wake"])
            self.assertTrue(data["belly_wake_enabled"])

    def test_set_power_encola_si_loading_y_dispara_clip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._fresh(tmp)
            clips: list[int] = []
            rs.on_not_ready_clip = lambda: clips.append(1)
            result = rs.set_power(True)
            self.assertEqual(result, "queued")
            self.assertEqual(clips, [1])
            data = rs.to_dict()
            self.assertTrue(data["power_on"])
            self.assertTrue(data["pending_wake"])
            self.assertFalse(data["models_ready"])

    def test_padre_resetea_playtime_al_prender(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._fresh(tmp)
            rs.sleep.mark_models_ready()
            rs.playtime_guard = PlaytimeGuard(limit_minutes=1)
            rs.playtime_guard.add_seconds(120)
            self.assertTrue(rs.playtime_guard.is_over_limit())
            rs.set_power(True)
            self.assertFalse(rs.playtime_guard.is_over_limit())
            self.assertEqual(rs.sleep.phase(), "awake")

    def test_belly_wake_se_persiste(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parental_prefs.json"
            rs = RobotState(prefs_path=path)
            rs.update_config({"belly_wake_enabled": False})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(saved["belly_wake_enabled"])
            rs2 = RobotState(prefs_path=path)
            self.assertFalse(rs2.sleep.belly_wake_enabled)
            self.assertFalse(rs2.to_dict()["belly_wake_enabled"])

    def test_activity_allowed_solo_despierto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._fresh(tmp)
            self.assertFalse(rs.activity_allowed())
            rs.sleep.mark_models_ready()
            self.assertFalse(rs.activity_allowed())
            rs.set_power(True)
            self.assertTrue(rs.activity_allowed())

    def _awake(self, tmp: str) -> RobotState:
        rs = self._fresh(tmp)
        rs.sleep.mark_models_ready()
        rs.set_power(True)
        return rs

    def test_panza_con_musica_corta_y_no_abraza(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._awake(tmp)
            stopped: list[str] = []
            rs.speech_worker = type("SW", (), {"_is_playing_music": True, "_story_guard": False})()
            rs.on_stop_music = lambda: stopped.append("stop")
            self.assertEqual(rs.apply_belly(), "stop")
            self.assertEqual(stopped, ["stop"])
            self.assertEqual(rs.sleep.phase(), "awake")

    def test_panza_con_cuento_corta_y_no_abraza(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._awake(tmp)
            stopped: list[str] = []
            rs.speech_worker = type("SW", (), {"_is_playing_music": False, "_story_guard": True})()
            rs.on_stop_music = lambda: stopped.append("stop")
            self.assertEqual(rs.apply_belly(), "stop")
            self.assertEqual(stopped, ["stop"])

    def test_panza_sin_repro_sigue_abrazo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._awake(tmp)
            stopped: list[str] = []
            rs.speech_worker = type("SW", (), {"_is_playing_music": False, "_story_guard": False})()
            rs.on_stop_music = lambda: stopped.append("stop")
            self.assertEqual(rs.apply_belly(), "hug")
            self.assertEqual(stopped, [])

    def test_panza_con_pipeline_de_oraciones_corta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._awake(tmp)
            stopped: list[str] = []
            rs.speech_worker = type(
                "SW",
                (),
                {"_is_playing_music": False, "_story_guard": False, "_pipeline_active": True},
            )()
            rs.on_stop_music = lambda: stopped.append("stop")
            self.assertEqual(rs.apply_belly(), "stop")
            self.assertEqual(stopped, ["stop"])

    def test_panza_dormido_con_musica_prende_no_corta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rs = self._fresh(tmp)
            rs.sleep.mark_models_ready()
            stopped: list[str] = []
            rs.speech_worker = type("SW", (), {"_is_playing_music": True, "_story_guard": False})()
            rs.on_stop_music = lambda: stopped.append("stop")
            self.assertEqual(rs.apply_belly(), "wake")
            self.assertEqual(stopped, [])


if __name__ == "__main__":
    unittest.main()
