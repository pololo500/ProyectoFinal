"""HAL del peluche: botón de panza, servos de abrazo y pictogramas.

Los pines BCM se leen de ``hardware_pins.json``. Mientras sean null, todo
se simula en software (TTS + ojos). Cuando Teo indique el cableado, alcanza
con completar esos números; no hace falta tocar el resto de la app.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from debug_logger import log_action

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PINS_PATH = APP_DIR / "hardware_pins.json"

_PICTOGRAM_BY_TRANSITION = {
    "higiene": "manos",
    "comida": "plato",
    "descanso": "luna",
    "orden": "caja",
    "juego": "pelota",
}


def pictogram_for_routine(transition_to: str) -> str | None:
    return _PICTOGRAM_BY_TRANSITION.get((transition_to or "").strip().lower())


@dataclass
class HardwarePins:
    hug_button_pin: int | None = None
    servo_left_pin: int | None = None
    servo_right_pin: int | None = None

    @property
    def button_ready(self) -> bool:
        return self.hug_button_pin is not None

    @property
    def servos_ready(self) -> bool:
        return self.servo_left_pin is not None and self.servo_right_pin is not None

    @property
    def gpio_ready(self) -> bool:
        return self.button_ready or self.servos_ready


def load_pins(path: Path | None = None) -> HardwarePins:
    target = path or DEFAULT_PINS_PATH
    if not target.exists():
        return HardwarePins()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return HardwarePins()

    def _pin(key: str) -> int | None:
        value = data.get(key)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return HardwarePins(
        hug_button_pin=_pin("hug_button_pin"),
        servo_left_pin=_pin("servo_left_pin"),
        servo_right_pin=_pin("servo_right_pin"),
    )


@dataclass
class ActuatorResult:
    ok: bool
    simulated: bool
    message: str = ""


class PhysicalCompanion:
    """Abrazo y botón. Sin pines: simula. Con pines: GPIO BCM en la Pi."""

    def __init__(self, pins: HardwarePins | None = None) -> None:
        self.pins = pins or load_pins()
        self.hug_count = 0
        self._button_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._gpio = None

    def hug(self) -> ActuatorResult:
        self.hug_count += 1
        if not self.pins.servos_ready:
            log_action("HW", "abrazo simulado (pines de servo pendientes)")
            return ActuatorResult(ok=True, simulated=True, message="simulado")
        try:
            self._move_servos()
            log_action("HW", "abrazo con servos")
            return ActuatorResult(ok=True, simulated=False, message="servos")
        except Exception as exc:
            log_action("HW", f"servos fallaron, simulo: {exc}")
            return ActuatorResult(ok=True, simulated=True, message=str(exc))

    def start_button_watch(self, on_press: Callable[[], None]) -> bool:
        if not self.pins.button_ready or self.pins.hug_button_pin is None:
            log_action("HW", "botón de panza no cableado todavía")
            return False
        self._stop.clear()
        self._button_thread = threading.Thread(
            target=self._watch_button,
            args=(on_press,),
            name="HugButton",
            daemon=True,
        )
        self._button_thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._cleanup_gpio()

    def _move_servos(self) -> None:
        gpio = self._ensure_gpio()
        left = self.pins.servo_left_pin
        right = self.pins.servo_right_pin
        if left is None or right is None:
            raise RuntimeError("pines de servo incompletos")
        # Pulso ~1.5 ms centro, 1.0 / 2.0 ms para cerrar el abrazo, 0.6 s, volver.
        import time

        def _pulse(pin: int, duty: float) -> None:
            gpio.setup(pin, gpio.OUT)
            pwm = gpio.PWM(pin, 50)
            pwm.start(duty)
            time.sleep(0.6)
            pwm.ChangeDutyCycle(7.5)
            time.sleep(0.4)
            pwm.stop()

        _pulse(left, 5.0)
        _pulse(right, 10.0)

    def _watch_button(self, on_press: Callable[[], None]) -> None:
        gpio = self._ensure_gpio()
        pin = self.pins.hug_button_pin
        if pin is None:
            return
        gpio.setup(pin, gpio.IN, pull_up_down=gpio.PUD_UP)
        last = 1
        while not self._stop.is_set():
            value = gpio.input(pin)
            if last == 1 and value == 0:
                try:
                    on_press()
                except Exception:
                    pass
                self._stop.wait(0.4)
            last = value
            self._stop.wait(0.05)

    def _ensure_gpio(self):
        if self._gpio is not None:
            return self._gpio
        import RPi.GPIO as GPIO  # type: ignore

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        self._gpio = GPIO
        return GPIO

    def _cleanup_gpio(self) -> None:
        if self._gpio is None:
            return
        try:
            self._gpio.cleanup()
        except Exception:
            pass
        self._gpio = None
