"""eye_display.py — Interfaz de ojos animados expresivos.

Renderiza ojos animados en un Canvas de tkinter para reflejar el estado
emocional detectado.  Diseñado para la pantalla del peluche (Raspberry Pi)
y como modo visual alternativo al panel de debug del PoC.

Expresiones soportadas:
  - neutral   : ojos abiertos normales con parpadeo natural
  - feliz     : ojos curvados (sonrisa)
  - triste    : ojos caídos, párpados bajos
  - sorprendido: ojos muy abiertos
  - enojado   : cejas fruncidas
  - escuchando: brillo sutil pulsante
  - hablando  : parpadeo rítmico suave
  - dormido   : ojos casi cerrados (modo noche / apagado)
  - pensando  : círculo de carga (LLM)


La interfaz es minimalista y no sobreestimulante, siguiendo los
lineamientos del proyecto para niños con TEA.
"""
from __future__ import annotations

import math
import tkinter as tk
from typing import Any

from eye_render import EyeAnimator


# ---------------------------------------------------------------------------
# Colores y configuración
# ---------------------------------------------------------------------------

# Paleta suave y cálida — no sobreestimulante
_BG_COLOR = "#1a1a2e"       # Fondo oscuro suave
_EYE_COLOR = "#e0f7fa"      # Blanco celeste suave
_PUPIL_COLOR = "#263238"     # Pupila oscura
_HIGHLIGHT_COLOR = "#ffffff" # Brillo del ojo
_EYELID_COLOR = "#1a1a2e"   # Mismo que fondo para "cerrar" ojos
_BROW_COLOR = "#b0bec5"     # Cejas


class EyeDisplay:
    """Renderiza ojos animados expresivos en un Canvas de tkinter.

    Los ojos se dibujan como elipses con párpados controlados por
    parámetros que se interpolan suavemente entre expresiones.
    """

    def __init__(self, canvas: tk.Canvas | None, animator: EyeAnimator | None = None) -> None:
        self.canvas = canvas
        self.width = 800
        self.height = 480
        self._anim = animator or EyeAnimator()
        self.lcd = None
        self._lcd_loop_started = False

        # Espejo de estado para el dibujo en canvas (el animador es la fuente).
        self._params = self._anim.params
        self._target_params = self._anim.target_params
        self._brightness = self._anim.brightness
        self._current_expression = self._anim.expression
        self._pulse_phase = self._anim.pulse_phase
        self._is_pulsing = self._anim.is_pulsing
        self._pictogram = self._anim.pictogram

        self._canvas_ids: dict[str, int] = {}

        if self.canvas is not None:
            self.canvas.configure(bg=_BG_COLOR, highlightthickness=0)
            self.canvas.bind("<Configure>", self._on_resize)
            self._animate()
        else:
            self._start_lcd_thread_if_needed()

    # ------------------------------------------------------------------
    # API Pública
    # ------------------------------------------------------------------

    def set_expression(self, expression: str, transition_ms: int = 300) -> None:
        """Transiciona suavemente a una nueva expresión."""
        self._anim.set_expression(expression, transition_ms)
        self._sync_from_animator()

    def set_brightness(self, level: float) -> None:
        """Ajusta el brillo de los ojos (0.0 a 1.0)."""
        self._anim.set_brightness(level)
        self._sync_from_animator()

    def set_pictogram(self, name: str | None) -> None:
        """Muestra un pictograma simple bajo los ojos (rutina / abrazo)."""
        self._anim.set_pictogram(name)
        self._sync_from_animator()

    def get_expression(self) -> str:
        """Retorna la expresión actual."""
        return self._anim.get_expression()

    def attach_hardware_lcd(self) -> bool:
        """Enciende la TFT ST7789 si está cableada. Devuelve True si hay LCD."""
        if self.lcd is not None:
            return True
        try:
            from lcd_panel import try_open_lcd

            self.lcd = try_open_lcd()
        except Exception:
            self.lcd = None
        if self.lcd is not None and self.canvas is None:
            self._start_lcd_thread_if_needed()
        return self.lcd is not None

    def stop(self) -> None:
        self._lcd_loop_started = False
        lcd = self.lcd
        self.lcd = None
        if lcd is not None:
            try:
                lcd.close()
            except Exception:
                pass

    def _sync_from_animator(self) -> None:
        self._params = self._anim.params
        self._target_params = self._anim.target_params
        self._brightness = self._anim.brightness
        self._current_expression = self._anim.expression
        self._pulse_phase = self._anim.pulse_phase
        self._is_pulsing = self._anim.is_pulsing
        self._pictogram = self._anim.pictogram

    # ------------------------------------------------------------------
    # Parámetros de expresión
    # ------------------------------------------------------------------

    @staticmethod
    def _expression_params(expression: str) -> dict[str, float]:
        """Retorna los parámetros target para cada expresión."""
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
        }
        return expressions.get(expression, expressions["neutral"])

    # ------------------------------------------------------------------
    # Renderizado
    # ------------------------------------------------------------------

    def _on_resize(self, event: Any) -> None:
        self.width = event.width
        self.height = event.height

    def _interpolate_params(self) -> None:
        """Interpola suavemente los parámetros actuales hacia el target."""
        lerp_speed = 0.15  # 0.0=lento, 1.0=instantáneo
        for key in self._params:
            current = self._params[key]
            target = self._target_params.get(key, current)
            self._params[key] = current + (target - current) * lerp_speed

    def _animate(self) -> None:
        """Loop principal de animación (~30fps)."""
        self._anim.tick()
        self._sync_from_animator()
        if self.canvas is not None:
            self._draw_eyes()
        self._blit_lcd()
        if self.canvas is not None:
            self.canvas.after(33, self._animate)

    def _start_lcd_thread_if_needed(self) -> None:
        if self.canvas is not None or self.lcd is None or self._lcd_loop_started:
            return
        import threading

        self._lcd_loop_started = True
        threading.Thread(target=self._lcd_loop, name="LcdEyes", daemon=True).start()

    def _lcd_loop(self) -> None:
        import time

        while self._lcd_loop_started and self.lcd is not None:
            self._anim.tick()
            self._sync_from_animator()
            self._blit_lcd()
            time.sleep(0.033)

    def _blit_lcd(self) -> None:
        lcd = self.lcd
        if lcd is None:
            return
        try:
            frame = self._anim.render(lcd.display_width, lcd.display_height)
            lcd.display(frame)
        except Exception:
            pass

    def _brightness_adjusted_color(self, hex_color: str) -> str:
        """Aplica el nivel de brillo a un color hex."""
        if self._brightness >= 1.0:
            return hex_color
        # Convertir hex a RGB, escalar, y volver a hex
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = int(r * self._brightness)
        g = int(g * self._brightness)
        b = int(b * self._brightness)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw_eyes(self) -> None:
        """Dibuja ambos ojos en el canvas."""
        self.canvas.delete("all")

        w = self.width
        h = self.height
        cx = w / 2
        cy = h / 2

        eye_open = self._params["eye_open"]
        eye_curve = self._params["eye_curve"]
        brow_angle = self._params["brow_angle"]
        pupil_size = self._params["pupil_size"]
        eye_width_mult = self._params["eye_width_mult"]

        # Pulso de brillo para "escuchando"
        pulse_mult = 1.0
        if self._is_pulsing and self._pulse_phase > 0:
            pulse_mult = 1.0 + 0.1 * math.sin(self._pulse_phase)

        # Dimensiones base de los ojos
        base_eye_w = min(w * 0.18, 140) * eye_width_mult
        base_eye_h = min(h * 0.35, 160) * eye_open * pulse_mult
        eye_spacing = min(w * 0.15, 120)

        # Posiciones de los ojos
        left_cx = cx - eye_spacing
        right_cx = cx + eye_spacing
        eye_cy = cy + eye_curve * 15

        eye_color = self._brightness_adjusted_color(_EYE_COLOR)
        pupil_color = _PUPIL_COLOR
        highlight_color = self._brightness_adjusted_color(_HIGHLIGHT_COLOR)
        brow_color = self._brightness_adjusted_color(_BROW_COLOR)

        for ecx in (left_cx, right_cx):
            is_left = ecx < cx

            # Sclera (ojo blanco) — elipse
            self.canvas.create_oval(
                ecx - base_eye_w,
                eye_cy - base_eye_h,
                ecx + base_eye_w,
                eye_cy + base_eye_h,
                fill=eye_color,
                outline="",
            )

            # Pupila
            p_size = base_eye_w * 0.45 * pupil_size
            p_y_offset = base_eye_h * 0.05  # ligeramente abajo del centro
            self.canvas.create_oval(
                ecx - p_size,
                eye_cy + p_y_offset - p_size,
                ecx + p_size,
                eye_cy + p_y_offset + p_size,
                fill=pupil_color,
                outline="",
            )

            # Brillo (reflejo en la pupila)
            hl_size = p_size * 0.3
            hl_offset_x = -p_size * 0.25
            hl_offset_y = -p_size * 0.3
            self.canvas.create_oval(
                ecx + hl_offset_x - hl_size,
                eye_cy + p_y_offset + hl_offset_y - hl_size,
                ecx + hl_offset_x + hl_size,
                eye_cy + p_y_offset + hl_offset_y + hl_size,
                fill=highlight_color,
                outline="",
            )

            # Cejas (líneas curvas arriba del ojo)
            if abs(brow_angle) > 0.05:
                brow_y_base = eye_cy - base_eye_h - 15
                brow_len = base_eye_w * 0.9

                # La ceja se inclina según la emoción
                if is_left:
                    angle_mult = -1
                else:
                    angle_mult = 1

                brow_y_inner = brow_y_base - brow_angle * 12 * angle_mult
                brow_y_outer = brow_y_base + brow_angle * 12 * angle_mult

                self.canvas.create_line(
                    ecx - brow_len, brow_y_inner,
                    ecx, brow_y_base - 5,
                    ecx + brow_len, brow_y_outer,
                    fill=brow_color,
                    width=max(3, base_eye_w * 0.06),
                    smooth=True,
                    capstyle="round",
                )

            # Párpado superior (para "cerrar" parcialmente)
            if eye_open < 0.95:
                lid_coverage = 1.0 - eye_open
                lid_h = base_eye_h * 1.3 * lid_coverage
                # El párpado es un rectángulo del color del fondo
                # que cubre la parte superior del ojo
                self.canvas.create_rectangle(
                    ecx - base_eye_w - 5,
                    eye_cy - base_eye_h - 20,
                    ecx + base_eye_w + 5,
                    eye_cy - base_eye_h + lid_h,
                    fill=_BG_COLOR,
                    outline="",
                )

            # Curvatura inferior para expresión feliz
            if eye_curve > 0.1:
                curve_h = base_eye_h * eye_curve * 0.6
                self.canvas.create_rectangle(
                    ecx - base_eye_w - 5,
                    eye_cy + base_eye_h - curve_h,
                    ecx + base_eye_w + 5,
                    eye_cy + base_eye_h + 20,
                    fill=_BG_COLOR,
                    outline="",
                )

        if self.canvas is not None:
            self._draw_pictogram(cx, cy, h)

    def _draw_pictogram(self, cx: float, cy: float, h: float) -> None:
        name = self._pictogram
        if not name:
            return
        labels = {
            "abrazo": "ABRAZO",
            "manos": "MANOS",
            "plato": "COMIDA",
            "luna": "DORMIR",
            "caja": "ORDEN",
            "pelota": "JUEGO",
        }
        label = labels.get(name, name.upper())
        color = self._brightness_adjusted_color(_HIGHLIGHT_COLOR)
        y = cy + min(h * 0.38, 160)
        self.canvas.create_text(
            cx,
            y,
            text=label,
            fill=color,
            font=("Segoe UI", 22, "bold"),
        )


def create_eye_display(canvas: tk.Canvas | None = None) -> EyeDisplay:
    """Crea ojos en canvas (Windows/HDMI) y, si hay hardware, en la LCD ST7789."""
    display = EyeDisplay(canvas)
    if display.attach_hardware_lcd():
        from debug_logger import log_action

        log_action("LCD", "ojos en pantalla ST7789")
    return display
