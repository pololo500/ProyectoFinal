"""Tests del comando de inversión ST7789 (sin SPI)."""
from __future__ import annotations

import unittest

from lcd_panel import invert_command


class TestInvertCommand(unittest.TestCase):
    def test_invert_off_es_0x20(self) -> None:
        self.assertEqual(invert_command(False), 0x20)

    def test_invert_on_es_0x21(self) -> None:
        self.assertEqual(invert_command(True), 0x21)


if __name__ == "__main__":
    unittest.main()
