"""Renderer de ojos expresivos (Pillow) para tkinter y la LCD ST7789."""
from __future__ import annotations

import math
import random
import time
from PIL import Image, ImageDraw, ImageFont

_BG = (26, 26, 46)
_EYE = (224, 247, 250)
_PUPIL = (38, 50, 56)
_HIGHLIGHT = (255, 255, 255)
_BROW = (176, 190, 197)

_PICTOGRAM_LABELS = {
    "abrazo": "ABRAZO",
    "manos": "MANOS",
    "plato": "COMIDA",
    "luna": "DORMIR",
    "caja": "ORDEN",
    "pelota": "JUEGO",
}


def image_to_rgb565(image: Image.Image) -> bytes:
    """Convierte una imagen RGB a RGB565 big-endian (ST7789)."""
    rgb = image.convert("RGB")
    try:
        import numpy as np

        pixels = np.array(rgb, dtype=np.uint16)
        packed = (
            ((pixels[:, :, 0] >> 3) << 11)
            | ((pixels[:, :, 1] >> 2) << 5)
            | (pixels[:, :, 2] >> 3)
        )
        return packed.astype(">u2").tobytes()
    except Exception:
        out = bytearray()
        for r, g, b in rgb.getdata():
            value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out.append((value >> 8) & 0xFF)
            out.append(value & 0xFF)
        return bytes(out)


def _scale_rgb(rgb: tuple[int, int, int], brightness: float) -> tuple[int, int, int]:
    level = max(0.0, min(1.0, brightness))
    return (
        int(rgb[0] * level),
        int(rgb[1] * level),
        int(rgb[2] * level),
    )


def _expression_params(expression: str) -> dict[str, float]:
    expressions = {
        "neutral": {
            "eye_open": 1.0,
            "eye_curve": 0.0,
            "brow_angle": 0.0,
            "pupil_size": 1.0,
            "eye_width_mult": 1.0,
        },
        "feliz": {
            "eye_open": 0.65,
            "eye_curve": 0.8,
            "brow_angle": -0.3,
            "pupil_size": 1.1,
            "eye_width_mult": 1.05,
        },
        "triste": {
            "eye_open": 0.55,
            "eye_curve": -0.3,
            "brow_angle": -0.7,
            "pupil_size": 0.9,
            "eye_width_mult": 0.95,
        },
        "sorprendido": {
            "eye_open": 1.4,
            "eye_curve": 0.0,
            "brow_angle": -0.5,
            "pupil_size": 1.4,
            "eye_width_mult": 1.15,
        },
        "enojado": {
            "eye_open": 0.7,
            "eye_curve": -0.1,
            "brow_angle": 0.8,
            "pupil_size": 0.85,
            "eye_width_mult": 1.0,
        },
        "escuchando": {
            "eye_open": 1.1,
            "eye_curve": 0.1,
            "brow_angle": -0.2,
            "pupil_size": 1.2,
            "eye_width_mult": 1.0,
        },
        "hablando": {
            "eye_open": 0.9,
            "eye_curve": 0.3,
            "brow_angle": 0.0,
            "pupil_size": 1.0,
            "eye_width_mult": 1.0,
        },
        "dormido": {
            "eye_open": 0.08,
            "eye_curve": 0.2,
            "brow_angle": 0.0,
            "pupil_size": 0.7,
            "eye_width_mult": 1.0,
        },
        "pensando": {
            "eye_open": 1.0,
            "eye_curve": 0.0,
            "brow_angle": 0.0,
            "pupil_size": 1.0,
            "eye_width_mult": 1.0,
        },
        "zzz": {
            "eye_open": 0.08,
            "eye_curve": 0.0,
            "brow_angle": 0.0,
            "pupil_size": 0.7,
            "eye_width_mult": 1.0,
        },
    }
    return expressions.get(expression, expressions["neutral"])


class EyeAnimator:
    """Estado y dibujo de los ojos, sin tkinter."""

    def __init__(self) -> None:
        self.params: dict[str, float] = {
            "eye_open": 1.0,
            "eye_curve": 0.0,
            "brow_angle": 0.0,
            "pupil_size": 1.0,
            "eye_width_mult": 1.0,
        }
        self.target_params: dict[str, float] = dict(self.params)
        self.brightness: float = 1.0
        self.expression: str = "neutral"
        self.is_pulsing: bool = False
        self.pulse_phase: float = 0.0
        self.pictogram: str | None = None
        self._pictogram_until: float = 0.0
        self._blink_mode: str = "idle"
        self._blink_step: int = 0
        self._next_blink_at: float = time.monotonic() + random.uniform(3.0, 6.0)

    def set_expression(self, expression: str, transition_ms: int = 300) -> None:
        del transition_ms
        self.expression = expression
        self.is_pulsing = expression in ("escuchando", "hablando", "pensando", "zzz")
        if expression in ("dormido", "zzz"):
            self._blink_mode = "idle"
        self.target_params.update(_expression_params(expression))

    def get_expression(self) -> str:
        return self.expression

    def set_brightness(self, level: float) -> None:
        self.brightness = max(0.0, min(1.0, level))

    def set_pictogram(self, name: str | None) -> None:
        self.pictogram = name
        if name:
            self._pictogram_until = time.monotonic() + 8.0

    def tick(self) -> None:
        lerp_speed = 0.15
        blinking = self._blink_mode != "idle"
        for key in self.params:
            if blinking and key == "eye_open":
                continue
            current = self.params[key]
            target = self.target_params.get(key, current)
            self.params[key] = current + (target - current) * lerp_speed
        if self.is_pulsing:
            self.pulse_phase += 0.08
        else:
            self.pulse_phase = 0.0
        now = time.monotonic()
        if self.pictogram and now >= self._pictogram_until:
            self.pictogram = None
        self._tick_blink(now)

    def _tick_blink(self, now: float) -> None:
        if self.expression in ("dormido", "pensando", "zzz"):
            return
        if self._blink_mode == "idle":
            if now >= self._next_blink_at:
                self._blink_mode = "closing"
                self._blink_step = 0
            return
        if self._blink_mode == "closing":
            self.params["eye_open"] = max(0.05, self.params["eye_open"] - 0.25)
            self._blink_step += 1
            if self._blink_step >= 4:
                self._blink_mode = "opening"
                self._blink_step = 0
            return
        target_open = self.target_params.get("eye_open", 1.0)
        self.params["eye_open"] = min(target_open, self.params["eye_open"] + 0.25)
        self._blink_step += 1
        if self._blink_step >= 4:
            self.params["eye_open"] = target_open
            self._blink_mode = "idle"
            self._next_blink_at = now + random.uniform(3.0, 6.0)

    def render(self, width: int, height: int) -> Image.Image:
        image = Image.new("RGB", (max(1, width), max(1, height)), _BG)
        draw = ImageDraw.Draw(image)
        self._draw(draw, width, height)
        return image

    def _draw(self, draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
        if self.expression == "zzz":
            self._draw_zzz(draw, w, h)
            return
        if self.expression == "pensando":
            self._draw_spinner(draw, w, h)
            return
        cx = w / 2
        cy = h / 2
        eye_open = self.params["eye_open"]
        eye_curve = self.params["eye_curve"]
        brow_angle = self.params["brow_angle"]
        pupil_size = self.params["pupil_size"]
        eye_width_mult = self.params["eye_width_mult"]
        pulse_mult = 1.0
        if self.is_pulsing and self.pulse_phase > 0:
            pulse_mult = 1.0 + 0.1 * math.sin(self.pulse_phase)
        base_eye_w = min(w * 0.18, 140) * eye_width_mult
        base_eye_h = min(h * 0.35, 160) * eye_open * pulse_mult
        eye_spacing = min(w * 0.15, 120)
        left_cx = cx - eye_spacing
        right_cx = cx + eye_spacing
        eye_cy = cy + eye_curve * 15
        eye_color = _scale_rgb(_EYE, self.brightness)
        highlight = _scale_rgb(_HIGHLIGHT, self.brightness)
        brow_color = _scale_rgb(_BROW, self.brightness)
        for ecx in (left_cx, right_cx):
            is_left = ecx < cx
            draw.ellipse(
                (
                    ecx - base_eye_w,
                    eye_cy - base_eye_h,
                    ecx + base_eye_w,
                    eye_cy + base_eye_h,
                ),
                fill=eye_color,
            )
            p_size = base_eye_w * 0.45 * pupil_size
            p_y_offset = base_eye_h * 0.05
            draw.ellipse(
                (
                    ecx - p_size,
                    eye_cy + p_y_offset - p_size,
                    ecx + p_size,
                    eye_cy + p_y_offset + p_size,
                ),
                fill=_PUPIL,
            )
            hl_size = p_size * 0.3
            hl_offset_x = -p_size * 0.25
            hl_offset_y = -p_size * 0.3
            draw.ellipse(
                (
                    ecx + hl_offset_x - hl_size,
                    eye_cy + p_y_offset + hl_offset_y - hl_size,
                    ecx + hl_offset_x + hl_size,
                    eye_cy + p_y_offset + hl_offset_y + hl_size,
                ),
                fill=highlight,
            )
            if abs(brow_angle) > 0.05:
                brow_y_base = eye_cy - base_eye_h - 15
                brow_len = base_eye_w * 0.9
                angle_mult = -1 if is_left else 1
                brow_y_inner = brow_y_base - brow_angle * 12 * angle_mult
                brow_y_outer = brow_y_base + brow_angle * 12 * angle_mult
                try:
                    draw.line(
                        [
                            (ecx - brow_len, brow_y_inner),
                            (ecx, brow_y_base - 5),
                            (ecx + brow_len, brow_y_outer),
                        ],
                        fill=brow_color,
                        width=max(3, int(base_eye_w * 0.06)),
                        joint="curve",
                    )
                except TypeError:
                    draw.line(
                        [
                            (ecx - brow_len, brow_y_inner),
                            (ecx, brow_y_base - 5),
                            (ecx + brow_len, brow_y_outer),
                        ],
                        fill=brow_color,
                        width=max(3, int(base_eye_w * 0.06)),
                    )
            if eye_open < 0.95:
                lid_coverage = 1.0 - eye_open
                lid_h = base_eye_h * 1.3 * lid_coverage
                draw.rectangle(
                    (
                        ecx - base_eye_w - 5,
                        eye_cy - base_eye_h - 20,
                        ecx + base_eye_w + 5,
                        eye_cy - base_eye_h + lid_h,
                    ),
                    fill=_BG,
                )
            if eye_curve > 0.1:
                curve_h = base_eye_h * eye_curve * 0.6
                draw.rectangle(
                    (
                        ecx - base_eye_w - 5,
                        eye_cy + base_eye_h - curve_h,
                        ecx + base_eye_w + 5,
                        eye_cy + base_eye_h + 20,
                    ),
                    fill=_BG,
                )
        if self.pictogram:
            label = _PICTOGRAM_LABELS.get(self.pictogram, self.pictogram.upper())
            color = _scale_rgb(_HIGHLIGHT, self.brightness)
            y = cy + min(h * 0.38, 160)
            font = _pictogram_font(max(12, int(h * 0.08)))
            draw.text((cx, y), label, fill=color, font=font, anchor="mm")

    def _draw_zzz(self, draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
        cx = w / 2
        cy = h / 2
        pulse = 1.0
        if self.is_pulsing:
            pulse = 0.82 + 0.18 * (0.5 + 0.5 * math.sin(self.pulse_phase))
        color = _scale_rgb((176, 230, 235), self.brightness * pulse)
        font = _pictogram_font(max(48, int(h * 0.36)))
        draw.text((cx, cy), "zzz", fill=color, font=font, anchor="mm")

    def _draw_spinner(self, draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
        cx = w / 2
        cy = h / 2
        radius = min(w, h) * 0.22
        width = max(8, int(radius * 0.18))
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        start = (self.pulse_phase * 40.0) % 360.0
        color = _scale_rgb((160, 230, 235), self.brightness)
        track = _scale_rgb((50, 70, 80), self.brightness)
        draw.arc(bbox, start=0, end=360, fill=track, width=width)
        draw.arc(bbox, start=start, end=start + 280, fill=color, width=width)


def _pictogram_font(size: int) -> ImageFont.ImageFont:
    for name in (
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
        "arial.ttf",
        "segoeui.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()
