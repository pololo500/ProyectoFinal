"""Tests TDD del HAL (pines pendientes = simulación software)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hardware import HardwarePins, PhysicalCompanion, load_pins, pictogram_for_routine


class TestHardwarePins(unittest.TestCase):
    def test_json_sin_pines_queda_simulado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_pins.json"
            path.write_text(
                json.dumps({"hug_button_pin": None, "servo_left_pin": None, "servo_right_pin": None}),
                encoding="utf-8",
            )
            pins = load_pins(path)
            self.assertFalse(pins.gpio_ready)
            self.assertIsNone(pins.hug_button_pin)

    def test_json_con_pines_bcm_queda_listo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_pins.json"
            path.write_text(
                json.dumps({"hug_button_pin": 17, "servo_left_pin": 18, "servo_right_pin": 13}),
                encoding="utf-8",
            )
            pins = load_pins(path)
            self.assertTrue(pins.gpio_ready)
            self.assertTrue(pins.servos_ready)
            self.assertTrue(pins.button_ready)
            self.assertEqual(pins.servo_left_pin, 18)

    def test_solo_boton_queda_listo_sin_servos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_pins.json"
            path.write_text(
                json.dumps({"hug_button_pin": 17, "servo_left_pin": None, "servo_right_pin": None}),
                encoding="utf-8",
            )
            pins = load_pins(path)
            self.assertTrue(pins.button_ready)
            self.assertFalse(pins.servos_ready)


class TestPhysicalCompanion(unittest.TestCase):
    def test_abrazo_sin_pines_no_revienta_y_avisa_simulado(self) -> None:
        companion = PhysicalCompanion(HardwarePins())
        result = companion.hug()
        self.assertTrue(result.ok)
        self.assertTrue(result.simulated)
        self.assertEqual(companion.hug_count, 1)

    def test_boton_sin_pines_no_arranca_gpio(self) -> None:
        companion = PhysicalCompanion(HardwarePins())
        self.assertFalse(companion.start_button_watch(lambda: None))


class TestPictograms(unittest.TestCase):
    def test_higiene_manos(self) -> None:
        self.assertEqual(pictogram_for_routine("higiene"), "manos")

    def test_comida_plato(self) -> None:
        self.assertEqual(pictogram_for_routine("comida"), "plato")

    def test_descanso_luna(self) -> None:
        self.assertEqual(pictogram_for_routine("descanso"), "luna")

    def test_desconocido_none(self) -> None:
        self.assertIsNone(pictogram_for_routine("xyz"))


if __name__ == "__main__":
    unittest.main()
