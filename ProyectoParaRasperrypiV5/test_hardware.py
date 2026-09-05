"""Tests TDD del HAL (botón panza, servos SG90, LCD ST7789)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from hardware import (
    DEFAULT_PINS_PATH,
    HUG_ASK_PHRASE,
    HardwarePins,
    PhysicalCompanion,
    get_companion,
    load_pins,
    perform_hug_ask,
    pictogram_for_routine,
    reset_companion_for_tests,
)


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


class TestCableadoRpi5(unittest.TestCase):
    def test_json_default_usa_pines_del_ensamble(self) -> None:
        pins = load_pins(DEFAULT_PINS_PATH)
        self.assertEqual(pins.hug_button_pin, 27)
        self.assertEqual(pins.servo_left_pin, 12)
        self.assertEqual(pins.servo_right_pin, 13)
        self.assertTrue(pins.button_ready)
        self.assertTrue(pins.servos_ready)
        self.assertTrue(pins.lcd_ready)
        self.assertEqual(pins.lcd_dc_pin, 24)
        self.assertEqual(pins.lcd_rst_pin, 25)
        self.assertEqual(pins.lcd_spi_port, 0)
        self.assertEqual(pins.lcd_spi_cs, 0)
        self.assertEqual(pins.lcd_width, 240)
        self.assertEqual(pins.lcd_height, 320)
        self.assertEqual(pins.lcd_rotation, 90)

    def test_json_con_lcd_queda_listo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_pins.json"
            path.write_text(
                json.dumps(
                    {
                        "hug_button_pin": 27,
                        "servo_left_pin": 12,
                        "servo_right_pin": 13,
                        "lcd_dc_pin": 24,
                        "lcd_rst_pin": 25,
                    }
                ),
                encoding="utf-8",
            )
            pins = load_pins(path)
            self.assertTrue(pins.lcd_ready)
            self.assertEqual(pins.lcd_dc_pin, 24)


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

    def test_get_companion_reusa_la_misma_instancia(self) -> None:
        reset_companion_for_tests()
        try:
            a = get_companion(HardwarePins())
            b = get_companion()
            self.assertIs(a, b)
        finally:
            reset_companion_for_tests()


class TestHugAsk(unittest.TestCase):
    def test_frase_pide_abrazo_en_voz_alta(self) -> None:
        self.assertIn("abrazo", HUG_ASK_PHRASE.lower())
        self.assertIn("quiero", HUG_ASK_PHRASE.lower())
        rules = json.loads((Path(__file__).resolve().parent / "intent_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules["hug_request"]["robot_ask"], HUG_ASK_PHRASE)

    def test_perform_hug_ask_mueve_brazos_y_habla(self) -> None:
        companion = PhysicalCompanion(HardwarePins())
        spoken: list[str] = []
        eyes = MagicMock()
        perform_hug_ask(companion, spoken.append, eyes)
        self.assertEqual(spoken, [HUG_ASK_PHRASE])
        self.assertEqual(companion.hug_count, 1)
        eyes.set_pictogram.assert_called_once_with("abrazo")
        eyes.set_expression.assert_called_once_with("feliz")


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
