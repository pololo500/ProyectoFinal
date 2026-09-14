"""Cámara: emoción a 5 fps."""
from __future__ import annotations

import queue
import unittest

from workers import CameraWorker


class TestCameraEmotionDefaults(unittest.TestCase):
    def test_emocion_encendida_a_5_fps(self) -> None:
        worker = CameraWorker(0, queue.Queue(), None, queue.Queue(), None)
        self.assertEqual(worker.frame_rate, 5)
        self.assertTrue(worker.infer_emotion)


if __name__ == "__main__":
    unittest.main()
