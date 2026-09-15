"""Al despertar, la LCD tiene que pasar de dormido al sprite Default (neutral)."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from app import EdgeAiDesktopApp, EyeModeApp


class TestApplySleepUiEyes(unittest.TestCase):
    def test_debug_despertar_pone_ojos_neutral(self) -> None:
        fake = MagicMock()
        fake._eye_display = MagicMock()
        EdgeAiDesktopApp._apply_sleep_ui(fake, True)
        fake._eye_display.set_expression.assert_called_with("neutral")

    def test_debug_dormir_pone_ojos_dormido(self) -> None:
        fake = MagicMock()
        fake._eye_display = MagicMock()
        EdgeAiDesktopApp._apply_sleep_ui(fake, False)
        fake._eye_display.set_expression.assert_called_with("dormido")

    def test_eye_mode_despertar_pone_ojos_neutral(self) -> None:
        fake = MagicMock()
        fake._eye_display = MagicMock()
        EyeModeApp._apply_sleep_ui(fake, True)
        fake._eye_display.set_expression.assert_called_with("neutral")
