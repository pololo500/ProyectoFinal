"""Clasificador PPT por landmarks, gate de 3 frames y sesión de juego."""
from __future__ import annotations

import queue
import random
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from game_engine import GameEngine, PiedraPapelTijeraSession
from rps_hand import (
    RpsGestureGate,
    boost_low_light_bgr,
    classify_rps_finger_count,
    classify_rps_landmarks,
    count_finger_valleys,
    hand_inference_size,
    low_light_gamma,
    merge_rps_guesses,
    rps_hand_landmarker_config,
)
from workers import (
    CAMERA_CAPTURE_PROBE_HEIGHT,
    CAMERA_CAPTURE_PROBE_WIDTH,
    CameraWorker,
    apply_camera_capture_size,
)


def _hand(*, extended: set[str]) -> list[tuple[float, float]]:
    """21 landmarks sintéticos. Muñeca abajo; punta más lejos = extendido."""
    pts = [(0.5, 0.92)] * 21
    pts[0] = (0.5, 0.92)
    fingers = {
        "index": (8, 6, 5),
        "middle": (12, 10, 9),
        "ring": (16, 14, 13),
        "pinky": (20, 18, 17),
    }
    x = 0.30
    for name, (tip, pip, mcp) in fingers.items():
        x += 0.08
        pts[mcp] = (x, 0.70)
        if name in extended:
            pts[pip] = (x, 0.45)
            pts[tip] = (x, 0.12)
        else:
            pts[pip] = (x, 0.68)
            pts[tip] = (x, 0.66)
    return pts


FIST = _hand(extended=set())
PALM = _hand(extended={"index", "middle", "ring", "pinky"})
SCISSORS = _hand(extended={"index", "middle"})
MIXED = _hand(extended={"index", "ring"})


def _leaky_fist() -> list[tuple[float, float]]:
    """Como MediaPipe en un puño real: puntas apenas más allá del PIP, pegadas al MCP."""
    pts = [(0.5, 0.92)] * 21
    pts[0] = (0.5, 0.92)
    xs = (0.34, 0.44, 0.54, 0.64)
    mcps, pips, tips = (5, 9, 13, 17), (6, 10, 14, 18), (8, 12, 16, 20)
    for x, mcp, pip, tip in zip(xs, mcps, pips, tips):
        pts[mcp] = (x, 0.70)
        pts[pip] = (x, 0.68)
        pts[tip] = (x, 0.66)
    return pts


def _leaky_scissors() -> list[tuple[float, float]]:
    pts = _leaky_fist()
    for mcp, pip, tip in ((5, 6, 8), (9, 10, 12)):
        x = pts[mcp][0]
        pts[pip] = (x, 0.45)
        pts[tip] = (x, 0.12)
    return pts


class TestClassifyRpsLandmarks(unittest.TestCase):
    def test_punio_es_piedra(self) -> None:
        guess = classify_rps_landmarks(FIST)
        self.assertEqual(guess.label, "piedra")
        self.assertGreaterEqual(guess.score, 0.65)

    def test_palma_es_papel(self) -> None:
        guess = classify_rps_landmarks(PALM)
        self.assertEqual(guess.label, "papel")
        self.assertGreaterEqual(guess.score, 0.65)

    def test_tijera_indice_y_medio(self) -> None:
        guess = classify_rps_landmarks(SCISSORS)
        self.assertEqual(guess.label, "tijera")
        self.assertGreaterEqual(guess.score, 0.65)

    def test_cero_puntos_es_none(self) -> None:
        guess = classify_rps_landmarks([])
        self.assertIsNone(guess.label)
        self.assertEqual(guess.score, 0.0)

    def test_incompleto_es_none(self) -> None:
        guess = classify_rps_landmarks([(0.0, 0.0)] * 10)
        self.assertIsNone(guess.label)

    def test_patron_mixto_es_none(self) -> None:
        guess = classify_rps_landmarks(MIXED)
        self.assertIsNone(guess.label)

    def test_punio_mediapipe_puntas_cerca_del_mcp_es_piedra(self) -> None:
        guess = classify_rps_landmarks(_leaky_fist())
        self.assertEqual(guess.label, "piedra")
        self.assertGreaterEqual(guess.score, 0.65)

    def test_tijera_con_anular_meñique_semiflex_es_tijera(self) -> None:
        guess = classify_rps_landmarks(_leaky_scissors())
        self.assertEqual(guess.label, "tijera")
        self.assertGreaterEqual(guess.score, 0.65)


class TestClassifyFingerCount(unittest.TestCase):
    def test_cero_es_piedra(self) -> None:
        guess = classify_rps_finger_count(0)
        self.assertEqual(guess.label, "piedra")
        self.assertGreaterEqual(guess.score, 0.65)

    def test_uno_es_piedra(self) -> None:
        self.assertEqual(classify_rps_finger_count(1).label, "piedra")

    def test_dos_es_tijera(self) -> None:
        self.assertEqual(classify_rps_finger_count(2).label, "tijera")

    def test_tres_es_tijera(self) -> None:
        self.assertEqual(classify_rps_finger_count(3).label, "tijera")

    def test_cinco_es_papel(self) -> None:
        self.assertEqual(classify_rps_finger_count(5).label, "papel")

    def test_none_es_none(self) -> None:
        guess = classify_rps_finger_count(None)
        self.assertIsNone(guess.label)


class TestMergeRpsGuesses(unittest.TestCase):
    def test_hands_gana_si_hay_label(self) -> None:
        from rps_hand import RpsGuess

        hands = RpsGuess(label="papel", score=0.9)
        sil = RpsGuess(label="piedra", score=0.8, source="silueta")
        merged = merge_rps_guesses(hands, sil)
        self.assertEqual(merged.label, "papel")
        self.assertEqual(merged.source, "hands")

    def test_silueta_si_hands_vacio(self) -> None:
        from rps_hand import RpsGuess

        hands = RpsGuess(label=None, score=0.4)
        sil = RpsGuess(label="tijera", score=0.8, source="silueta")
        merged = merge_rps_guesses(hands, sil)
        self.assertEqual(merged.label, "tijera")
        self.assertEqual(merged.source, "silueta")


class TestCountFingerValleys(unittest.TestCase):
    def test_sin_valleys_es_cero_dedos(self) -> None:
        self.assertEqual(count_finger_valleys([], [], [], [], min_depth=10.0), 0)

    def test_un_valley_profundo_es_tijera(self) -> None:
        # V: far abajo, start/end arriba a los lados.
        n = count_finger_valleys(
            starts=[(0.0, 0.0)],
            ends=[(20.0, 0.0)],
            fars=[(10.0, 30.0)],
            depths=[40.0],
            min_depth=10.0,
        )
        self.assertEqual(n, 2)

    def test_valley_poco_profundo_se_ignora(self) -> None:
        n = count_finger_valleys(
            starts=[(0.0, 0.0)],
            ends=[(20.0, 0.0)],
            fars=[(10.0, 30.0)],
            depths=[2.0],
            min_depth=10.0,
        )
        self.assertEqual(n, 0)


class TestHandInferenceSize(unittest.TestCase):
    def test_720p_baja_a_640(self) -> None:
        self.assertEqual(hand_inference_size(1280, 720), (640, 480))

    def test_640_no_cambia(self) -> None:
        self.assertEqual(hand_inference_size(640, 480), (640, 480))


class TestLowLightBoost(unittest.TestCase):
    def test_luz_normal_no_gamma(self) -> None:
        self.assertAlmostEqual(low_light_gamma(120.0), 1.0)

    def test_luz_baja_gamma_menor_a_uno(self) -> None:
        self.assertLess(low_light_gamma(30.0), 0.75)

    def test_frame_oscuro_sube_el_brillo_medio(self) -> None:
        import numpy as np

        dark = np.full((20, 20, 3), 40, dtype=np.uint8)
        boosted = boost_low_light_bgr(dark)
        self.assertGreater(float(boosted.mean()), float(dark.mean()))

    def test_frame_claro_no_cambia(self) -> None:
        import numpy as np

        bright = np.full((20, 20, 3), 160, dtype=np.uint8)
        boosted = boost_low_light_bgr(bright)
        self.assertEqual(int(boosted.mean()), int(bright.mean()))


class TestRpsGestureGate(unittest.TestCase):
    def test_dos_frames_no_cierran(self) -> None:
        gate = RpsGestureGate()
        gate.observe("papel", 0.9)
        gate.observe("papel", 0.9)
        self.assertIsNone(gate.confident_choice())
        self.assertFalse(gate.saw_confident)

    def test_tres_iguales_cierran(self) -> None:
        gate = RpsGestureGate()
        for _ in range(3):
            gate.observe("tijera", 0.8)
        self.assertEqual(gate.confident_choice(), "tijera")
        self.assertTrue(gate.saw_confident)

    def test_score_bajo_no_cuenta(self) -> None:
        gate = RpsGestureGate()
        for _ in range(5):
            gate.observe("piedra", 0.4)
        self.assertIsNone(gate.confident_choice())
        self.assertFalse(gate.saw_confident)

    def test_frame_distinto_reinicia_racha(self) -> None:
        gate = RpsGestureGate()
        gate.observe("papel", 0.9)
        gate.observe("papel", 0.9)
        gate.observe("piedra", 0.9)
        gate.observe("papel", 0.9)
        self.assertIsNone(gate.confident_choice())
        gate.observe("papel", 0.9)
        gate.observe("papel", 0.9)
        self.assertEqual(gate.confident_choice(), "papel")

    def test_reset_round_limpia_confident(self) -> None:
        gate = RpsGestureGate()
        for _ in range(3):
            gate.observe("papel", 0.9)
        gate.reset_round()
        self.assertFalse(gate.saw_confident)
        self.assertIsNone(gate.confident_choice())


class TestPiedraPapelSessionChoice(unittest.TestCase):
    def test_process_choice_equivale_a_input(self) -> None:
        with patch("game_engine.random.choice", return_value="piedra"):
            by_choice = PiedraPapelTijeraSession().process_choice("papel")
            by_voice = PiedraPapelTijeraSession().process_input("papel")
        self.assertEqual(by_choice.text, by_voice.text)
        self.assertFalse(by_choice.game_over)
        self.assertIn("Yo elegí piedra", by_choice.text)

    def test_primer_vacio_pide_mano(self) -> None:
        session = PiedraPapelTijeraSession()
        resp = session.process_input("banana")
        self.assertIn("Mostrame la mano", resp.text)
        self.assertIn("piedra, papel o tijera", resp.text)
        self.assertEqual(session.rounds_played, 0)
        self.assertFalse(resp.game_over)

    def test_segundo_vacio_no_entendi(self) -> None:
        session = PiedraPapelTijeraSession()
        session.process_input("")
        resp = session.process_input("banana")
        self.assertIn("No entendí tu elección", resp.text)
        self.assertEqual(session.rounds_played, 0)

    def test_eleccion_valida_resetea_reintentos(self) -> None:
        session = PiedraPapelTijeraSession()
        session.process_input("banana")
        with patch("game_engine.random.choice", return_value="piedra"):
            session.process_choice("papel")
        resp = session.process_input("xyz")
        self.assertIn("Mostrame la mano", resp.text)

    def test_basta_termina(self) -> None:
        session = PiedraPapelTijeraSession()
        resp = session.process_input("basta")
        self.assertTrue(resp.game_over)

    def test_tiguera_sigue_siendo_tijera(self) -> None:
        session = PiedraPapelTijeraSession()
        resp = session.process_input("¡Tiguera!")
        self.assertNotIn("No entendí", resp.text)
        self.assertNotIn("Mostrame la mano", resp.text)
        self.assertEqual(session.rounds_played, 1)


class TestGameEngineCommitChoice(unittest.TestCase):
    def test_commit_choice_una_vez_por_ronda(self) -> None:
        engine = GameEngine()
        engine.start_game("piedra_papel_tijera")
        random.seed(2)
        first = engine.commit_choice("papel")
        self.assertIsNotNone(first)
        self.assertIn("Yo elegí", first.text)
        second = engine.commit_choice("piedra")
        self.assertIsNone(second)
        self.assertEqual(engine._session.rounds_played, 1)

    def test_stt_no_pisa_si_saw_confident(self) -> None:
        engine = GameEngine()
        engine.start_game("piedra_papel_tijera")
        random.seed(3)
        engine.commit_choice("papel")
        before = engine._session.rounds_played
        resp = engine.process_input("piedra", saw_confident=True)
        self.assertEqual(engine._session.rounds_played, before)
        self.assertFalse(resp.game_over)
        self.assertEqual(resp.text, "")

    def test_waiting_rps_choice(self) -> None:
        engine = GameEngine()
        self.assertFalse(engine.waiting_rps_choice)
        engine.start_game("piedra_papel_tijera")
        self.assertTrue(engine.waiting_rps_choice)
        engine.start_game("veo_veo")
        self.assertFalse(engine.waiting_rps_choice)


class TestCameraRpsFlag(unittest.TestCase):
    def test_hands_apagado_por_defecto(self) -> None:
        worker = CameraWorker(0, queue.Queue(), None, queue.Queue(), None)
        self.assertFalse(worker.rps_hands_enabled)
        worker.set_rps_hands_enabled(True)
        self.assertTrue(worker.rps_hands_enabled)
        worker.set_rps_hands_enabled(False)
        self.assertFalse(worker.rps_hands_enabled)

    def test_landmarker_image_mode_umbral_bajo(self) -> None:
        cfg = rps_hand_landmarker_config()
        self.assertEqual(cfg["running_mode"], "IMAGE")
        self.assertAlmostEqual(cfg["min_hand_detection_confidence"], 0.2)
        self.assertEqual(cfg["num_hands"], 2)

    def test_process_hands_usa_detect_no_video(self) -> None:
        import numpy as np

        worker = CameraWorker(0, queue.Queue(), None, queue.Queue(), None)
        landmarker = MagicMock()
        result = MagicMock()
        result.hand_landmarks = []
        landmarker.detect.return_value = result
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        worker._process_hands_frame(landmarker, frame)
        landmarker.detect.assert_called()
        landmarker.detect_for_video.assert_not_called()

    def test_sin_landmarks_usa_silueta(self) -> None:
        import numpy as np
        from rps_hand import RpsGuess

        worker = CameraWorker(0, queue.Queue(), None, queue.Queue(), None)
        landmarker = MagicMock()
        result = MagicMock()
        result.hand_landmarks = []
        landmarker.detect.return_value = result
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        sil = RpsGuess(label="piedra", score=0.8, source="silueta")
        with patch("workers.silhouette_rps_guess", return_value=sil):
            _annotated, guess = worker._process_hands_frame(landmarker, frame)
        self.assertEqual(guess.label, "piedra")
        self.assertEqual(guess.source, "silueta")


class _FakeCapture:
    def __init__(
        self,
        honor_set: bool = True,
        actual_w: float = 320.0,
        actual_h: float = 240.0,
        max_w: float = 1920.0,
        max_h: float = 1080.0,
    ) -> None:
        self.honor_set = honor_set
        self._props: dict[object, float] = {}
        self.actual_w = actual_w
        self.actual_h = actual_h
        self.max_w = max_w
        self.max_h = max_h

    def set(self, prop: object, value: float) -> bool:
        import cv2

        try:
            stored = float(value)
        except (TypeError, ValueError):
            self._props[prop] = value
            return True
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            stored = min(stored, float(self.max_w))
        elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
            stored = min(stored, float(self.max_h))
        self._props[prop] = stored
        return True

    def get(self, prop: object) -> float:
        import cv2

        if self.honor_set:
            return self._props.get(prop, 0.0)
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self.actual_w
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self.actual_h
        return 0.0


class TestCameraCaptureSize(unittest.TestCase):
    def test_probe_pide_tamano_grande(self) -> None:
        self.assertGreaterEqual(CAMERA_CAPTURE_PROBE_WIDTH, 1920)
        self.assertGreaterEqual(CAMERA_CAPTURE_PROBE_HEIGHT, 1080)

    def test_apply_usa_el_maximo_del_driver(self) -> None:
        cap = _FakeCapture(honor_set=True, max_w=1920.0, max_h=1080.0)
        w, h = apply_camera_capture_size(cap)
        self.assertEqual((w, h), (1920, 1080))

    def test_apply_si_driver_ignora_devuelve_real(self) -> None:
        cap = _FakeCapture(honor_set=False, actual_w=640.0, actual_h=480.0)
        w, h = apply_camera_capture_size(cap)
        self.assertEqual((w, h), (640, 480))

    def test_apply_restaura_auto_exposure_uvc(self) -> None:
        import cv2

        cap = _FakeCapture(honor_set=True)
        apply_camera_capture_size(cap)
        self.assertEqual(cap._props.get(cv2.CAP_PROP_AUTO_EXPOSURE), 3.0)
        self.assertNotIn(cv2.CAP_PROP_BRIGHTNESS, cap._props)
        self.assertNotIn(cv2.CAP_PROP_GAIN, cap._props)

    def test_run_no_pide_320_literal(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(encoding="utf-8")
        self.assertNotIn("capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)", src)
        self.assertIn("apply_camera_capture_size(capture)", src)


if __name__ == "__main__":
    unittest.main()
