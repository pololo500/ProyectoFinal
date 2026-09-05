"""Driver mínimo ST7789V (SPI) para la TFT 2.4\" del peluche."""
from __future__ import annotations

import time
from typing import Any

from PIL import Image

from debug_logger import log_action
from eye_render import image_to_rgb565
from hardware import HardwarePins, get_gpio, load_pins

# Comandos ST7789
_SWRESET = 0x01
_SLPOUT = 0x11
_NORON = 0x13
_INVON = 0x21
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C
_MADCTL = 0x36
_COLMOD = 0x3A
_COLMOD_16BIT = 0x55


def _madctl_for_rotation(rotation: int) -> int:
    # MX=0x40, MY=0x80, MV=0x20. 90° = paisaje 320x240 para dos ojos.
    table = {
        0: 0x00,
        90: 0x60,
        180: 0xC0,
        270: 0xA0,
    }
    return table.get(int(rotation) % 360, 0x60)


class St7789Panel:
    """Pantalla SPI ST7789. Backlight cableada a 3.3V (sin pin BLK por software)."""

    def __init__(self, pins: HardwarePins | None = None) -> None:
        self.pins = pins or load_pins()
        if not self.pins.lcd_ready or self.pins.lcd_dc_pin is None or self.pins.lcd_rst_pin is None:
            raise RuntimeError("pines LCD incompletos")
        self.native_width = self.pins.lcd_width
        self.native_height = self.pins.lcd_height
        self.rotation = self.pins.lcd_rotation
        if self.rotation % 180 == 90:
            self.display_width = self.native_height
            self.display_height = self.native_width
        else:
            self.display_width = self.native_width
            self.display_height = self.native_height
        self._gpio = get_gpio()
        self._dc = self.pins.lcd_dc_pin
        self._rst = self.pins.lcd_rst_pin
        self._gpio.setup_output(self._dc, 0)
        self._gpio.setup_output(self._rst, 1)
        self._spi = self._open_spi()
        self._reset()
        self._init()

    def _open_spi(self) -> Any:
        import spidev  # type: ignore

        spi = spidev.SpiDev()
        spi.open(self.pins.lcd_spi_port, self.pins.lcd_spi_cs)
        spi.mode = 0
        spi.max_speed_hz = 40_000_000
        spi.no_cs = False
        return spi

    def _reset(self) -> None:
        self._gpio.write(self._rst, 1)
        time.sleep(0.01)
        self._gpio.write(self._rst, 0)
        time.sleep(0.02)
        self._gpio.write(self._rst, 1)
        time.sleep(0.12)

    def _command(self, cmd: int, data: bytes | None = None) -> None:
        self._gpio.write(self._dc, 0)
        self._spi.writebytes([cmd & 0xFF])
        if data:
            self._gpio.write(self._dc, 1)
            self._write(data)

    def _write(self, payload: bytes | list[int]) -> None:
        if not payload:
            return
        data = payload if isinstance(payload, bytes) else bytes(payload)
        chunk = 4096
        writer = getattr(self._spi, "writebytes2", None)
        for i in range(0, len(data), chunk):
            piece = data[i : i + chunk]
            if writer is not None:
                writer(piece)
            else:
                self._spi.writebytes(list(piece))

    def _window(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._command(
            _CASET,
            bytes(
                [
                    (x0 >> 8) & 0xFF,
                    x0 & 0xFF,
                    (x1 >> 8) & 0xFF,
                    x1 & 0xFF,
                ]
            ),
        )
        self._command(
            _RASET,
            bytes(
                [
                    (y0 >> 8) & 0xFF,
                    y0 & 0xFF,
                    (y1 >> 8) & 0xFF,
                    y1 & 0xFF,
                ]
            ),
        )

    def _init(self) -> None:
        self._command(_SWRESET)
        time.sleep(0.15)
        self._command(_SLPOUT)
        time.sleep(0.12)
        self._command(_COLMOD, bytes([_COLMOD_16BIT]))
        self._command(_MADCTL, bytes([_madctl_for_rotation(self.rotation)]))
        self._command(_INVON)
        self._command(_NORON)
        self._command(_DISPON)
        time.sleep(0.02)
        self.fill((26, 26, 46))
        log_action(
            "LCD",
            f"ST7789 {self.display_width}x{self.display_height} rot={self.rotation}",
        )

    def fill(self, rgb: tuple[int, int, int]) -> None:
        image = Image.new("RGB", (self.display_width, self.display_height), rgb)
        self.display(image)

    def display(self, image: Image.Image) -> None:
        if image.size != (self.display_width, self.display_height):
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            image = image.resize((self.display_width, self.display_height), resample)
        payload = image_to_rgb565(image)
        x1 = self.display_width - 1
        y1 = self.display_height - 1
        self._window(0, 0, x1, y1)
        self._command(_RAMWR)
        self._gpio.write(self._dc, 1)
        self._write(payload)

    def close(self) -> None:
        try:
            self._spi.close()
        except Exception:
            pass


def try_open_lcd(pins: HardwarePins | None = None) -> St7789Panel | None:
    pins = pins or load_pins()
    if not pins.lcd_ready:
        return None
    try:
        return St7789Panel(pins)
    except Exception as exc:
        log_action("LCD", f"ST7789 no disponible: {exc}")
        return None
