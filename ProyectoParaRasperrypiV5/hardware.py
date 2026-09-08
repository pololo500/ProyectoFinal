"""HAL del peluche: botón de panza, servos SG90 y pines de la LCD ST7789.

Los pines BCM se leen de ``hardware_pins.json``. En Windows (sin GPIO) el
abrazo se simula. En la Raspberry Pi 5 se usa lgpio; si no está, RPi.GPIO.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from debug_logger import log_action

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PINS_PATH = APP_DIR / "hardware_pins.json"

HUG_ASK_PHRASE = "Quiero un abrazo. ¿Me das uno?"

_PICTOGRAM_BY_TRANSITION = {
    "higiene": "manos",
    "comida": "plato",
    "descanso": "luna",
    "orden": "caja",
    "juego": "pelota",
}

# SG90 a 50 Hz: 7.5 % ≈ 90° (reposo). Izquierda/derecha espejados para levantar.
SERVO_REST_DUTY = 7.5
SERVO_LEFT_UP_DUTY = 5.0
SERVO_RIGHT_UP_DUTY = 10.0


def pictogram_for_routine(transition_to: str) -> str | None:
    return _PICTOGRAM_BY_TRANSITION.get((transition_to or "").strip().lower())


@dataclass
class HardwarePins:
    hug_button_pin: int | None = None
    servo_left_pin: int | None = None
    servo_right_pin: int | None = None
    lcd_dc_pin: int | None = None
    lcd_rst_pin: int | None = None
    lcd_spi_port: int = 0
    lcd_spi_cs: int = 0
    lcd_width: int = 240
    lcd_height: int = 320
    lcd_rotation: int = 90

    @property
    def button_ready(self) -> bool:
        return self.hug_button_pin is not None

    @property
    def servos_ready(self) -> bool:
        return self.servo_left_pin is not None and self.servo_right_pin is not None

    @property
    def gpio_ready(self) -> bool:
        return self.button_ready or self.servos_ready

    @property
    def lcd_ready(self) -> bool:
        return self.lcd_dc_pin is not None and self.lcd_rst_pin is not None


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

    def _int(key: str, default: int) -> int:
        value = data.get(key, default)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return HardwarePins(
        hug_button_pin=_pin("hug_button_pin"),
        servo_left_pin=_pin("servo_left_pin"),
        servo_right_pin=_pin("servo_right_pin"),
        lcd_dc_pin=_pin("lcd_dc_pin"),
        lcd_rst_pin=_pin("lcd_rst_pin"),
        lcd_spi_port=_int("lcd_spi_port", 0),
        lcd_spi_cs=_int("lcd_spi_cs", 0),
        lcd_width=_int("lcd_width", 240),
        lcd_height=_int("lcd_height", 320),
        lcd_rotation=_int("lcd_rotation", 90),
    )


@dataclass
class ActuatorResult:
    ok: bool
    simulated: bool
    message: str = ""


class SharedGpio:
    """GPIO compartido (servos, pulsador, DC/RST de la LCD). Pi 5: lgpio."""

    def __init__(self) -> None:
        self._backend = ""
        self._lg: Any = None
        self._handle: int | None = None
        self._rpi: Any = None
        self._pwms: dict[int, Any] = {}
        self._claimed: set[int] = set()
        self._open()

    def _open(self) -> None:
        try:
            import lgpio  # type: ignore

            last: Exception | None = None
            for chip in (4, 0, 1):
                try:
                    handle = lgpio.gpiochip_open(chip)
                    self._lg = lgpio
                    self._handle = handle
                    self._backend = "lgpio"
                    log_action("HW", f"GPIO lgpio chip={chip}")
                    return
                except Exception as exc:
                    last = exc
            raise RuntimeError(str(last) if last else "lgpio sin chip")
        except Exception:
            try:
                import RPi.GPIO as GPIO  # type: ignore
            except ImportError as rpi_exc:
                raise RuntimeError(
                    "GPIO: falta lgpio en el venv (Pi 5). "
                    "En el venv: pip install lgpio spidev"
                ) from rpi_exc

            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            self._rpi = GPIO
            self._backend = "RPi.GPIO"
            log_action("HW", "GPIO RPi.GPIO")

    def setup_input_pullup(self, pin: int) -> None:
        if self._lg is not None and self._handle is not None:
            self._lg.gpio_claim_input(self._handle, pin, self._lg.SET_PULL_UP)
            self._claimed.add(pin)
            return
        self._rpi.setup(pin, self._rpi.IN, pull_up_down=self._rpi.PUD_UP)
        self._claimed.add(pin)

    def setup_output(self, pin: int, initial: int = 0) -> None:
        if pin in self._claimed:
            self.write(pin, initial)
            return
        if self._lg is not None and self._handle is not None:
            self._lg.gpio_claim_output(self._handle, pin, initial)
            self._claimed.add(pin)
            return
        self._rpi.setup(pin, self._rpi.OUT, initial=initial)
        self._claimed.add(pin)

    def write(self, pin: int, value: int) -> None:
        if self._lg is not None and self._handle is not None:
            self._lg.gpio_write(self._handle, pin, 1 if value else 0)
            return
        self._rpi.output(pin, self._rpi.HIGH if value else self._rpi.LOW)

    def read(self, pin: int) -> int:
        if self._lg is not None and self._handle is not None:
            return int(self._lg.gpio_read(self._handle, pin))
        return int(self._rpi.input(pin))

    def pwm_start(self, pin: int, duty: float) -> None:
        self.setup_output(pin, 0)
        if self._lg is not None and self._handle is not None:
            self._lg.tx_pwm(self._handle, pin, 50, float(duty))
            return
        pwm = self._pwms.get(pin)
        if pwm is None:
            pwm = self._rpi.PWM(pin, 50)
            pwm.start(duty)
            self._pwms[pin] = pwm
        else:
            pwm.ChangeDutyCycle(duty)

    def pwm_set(self, pin: int, duty: float) -> None:
        if self._lg is not None and self._handle is not None:
            self._lg.tx_pwm(self._handle, pin, 50, float(duty))
            return
        pwm = self._pwms.get(pin)
        if pwm is not None:
            pwm.ChangeDutyCycle(duty)

    def pwm_stop(self, pin: int) -> None:
        if self._lg is not None and self._handle is not None:
            try:
                self._lg.tx_pwm(self._handle, pin, 0, 0)
            except Exception:
                pass
            return
        pwm = self._pwms.pop(pin, None)
        if pwm is not None:
            try:
                pwm.stop()
            except Exception:
                pass

    def close(self) -> None:
        if self._lg is not None and self._handle is not None:
            try:
                self._lg.gpiochip_close(self._handle)
            except Exception:
                pass
            self._handle = None
            self._lg = None
            return
        if self._rpi is not None:
            try:
                self._rpi.cleanup()
            except Exception:
                pass
            self._rpi = None


_gpio_lock = threading.Lock()
_gpio_instance: SharedGpio | None = None
_companion_lock = threading.Lock()
_companion_instance: PhysicalCompanion | None = None


def get_gpio() -> SharedGpio:
    global _gpio_instance
    with _gpio_lock:
        if _gpio_instance is None:
            _gpio_instance = SharedGpio()
        return _gpio_instance


def reset_gpio_for_tests() -> None:
    global _gpio_instance
    with _gpio_lock:
        if _gpio_instance is not None:
            try:
                _gpio_instance.close()
            except Exception:
                pass
            _gpio_instance = None


class PhysicalCompanion:
    """Abrazo y botón. Sin pines o sin GPIO: simula. Con pines: BCM en la Pi."""

    def __init__(self, pins: HardwarePins | None = None) -> None:
        self.pins = pins or load_pins()
        self.hug_count = 0
        self._button_thread: threading.Thread | None = None
        self._stop = threading.Event()

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
        try:
            gpio = get_gpio()
            gpio.setup_input_pullup(self.pins.hug_button_pin)
        except Exception as exc:
            log_action("HW", f"GPIO no disponible para el pulsador: {exc}")
            return False
        self._stop.clear()
        self._button_thread = threading.Thread(
            target=self._watch_button,
            args=(on_press,),
            name="HugButton",
            daemon=True,
        )
        self._button_thread.start()
        log_action("HW", f"pulsador en GPIO {self.pins.hug_button_pin} (pull-up)")
        return True

    def stop(self) -> None:
        self._stop.set()
        left = self.pins.servo_left_pin
        right = self.pins.servo_right_pin
        if _gpio_instance is not None:
            if left is not None:
                _gpio_instance.pwm_stop(left)
            if right is not None:
                _gpio_instance.pwm_stop(right)

    def _move_servos(self) -> None:
        gpio = get_gpio()
        left = self.pins.servo_left_pin
        right = self.pins.servo_right_pin
        if left is None or right is None:
            raise RuntimeError("pines de servo incompletos")
        import time

        gpio.pwm_start(left, SERVO_LEFT_UP_DUTY)
        gpio.pwm_start(right, SERVO_RIGHT_UP_DUTY)
        time.sleep(1.0)
        gpio.pwm_set(left, SERVO_REST_DUTY)
        gpio.pwm_set(right, SERVO_REST_DUTY)
        time.sleep(0.45)
        gpio.pwm_stop(left)
        gpio.pwm_stop(right)

    def _watch_button(self, on_press: Callable[[], None]) -> None:
        gpio = get_gpio()
        pin = self.pins.hug_button_pin
        if pin is None:
            return
        last = 1
        while not self._stop.is_set():
            try:
                value = gpio.read(pin)
            except Exception:
                break
            if last == 1 and value == 0:
                try:
                    on_press()
                except Exception:
                    pass
                self._stop.wait(0.4)
            last = value
            self._stop.wait(0.05)


def get_companion(pins: HardwarePins | None = None) -> PhysicalCompanion:
    global _companion_instance
    with _companion_lock:
        if _companion_instance is None:
            _companion_instance = PhysicalCompanion(pins or load_pins())
        return _companion_instance


def reset_companion_for_tests() -> None:
    global _companion_instance
    with _companion_lock:
        if _companion_instance is not None:
            try:
                _companion_instance.stop()
            except Exception:
                pass
            _companion_instance = None


def perform_hug_ask(
    companion: PhysicalCompanion | None,
    speak: Callable[[str], None] | None,
    eyes: Any | None = None,
) -> None:
    """Pulsador: pide un abrazo en voz alta, ojos felices y levanta los brazos."""
    if speak is not None:
        speak(HUG_ASK_PHRASE)
    if eyes is not None:
        if hasattr(eyes, "set_pictogram"):
            eyes.set_pictogram("abrazo")
        if hasattr(eyes, "set_expression"):
            eyes.set_expression("feliz")
    if companion is not None:
        companion.hug()
