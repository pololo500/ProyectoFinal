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

La interfaz es minimalista y no sobreestimulante, siguiendo los
lineamientos del proyecto para niños con TEA.
"""
from __future__ import annotations

import math
import random
import tkinter as tk
from typing import Any


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

    def __init__(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.width = 800
        self.height = 480

        # Estado actual de la expresión (parámetros interpolados)
        self._params: dict[str, float] = {
            "eye_open": 1.0,      # 0.0 = cerrado, 1.0 = abierto completo
            "eye_curve": 0.0,     # 0.0 = recto, 1.0 = curvado (sonrisa)
            "brow_angle": 0.0,    # -1.0 = triste, 0.0 = neutral, 1.0 = enojado
            "pupil_size": 1.0,    # 0.5 = chica, 1.0 = normal, 1.5 = grande
            "eye_width_mult": 1.0,  # multiplicador de ancho
        }
        self._target_params: dict[str, float] = dict(self._params)
        self._brightness: float = 1.0  # 0.0 a 1.0
        self._current_expression: str = "neutral"
        self._blink_phase: float = 0.0
        self._is_blinking: bool = False
        self._pulse_phase: float = 0.0
        self._is_pulsing: bool = False  # Para "escuchando"

        # IDs de elementos del canvas para updates eficientes
        self._canvas_ids: dict[str, int] = {}

        # Configurar canvas
        self.canvas.configure(bg=_BG_COLOR, highlightthickness=0)
        self.canvas.bind("<Configure>", self._on_resize)

        # Iniciar loops de animación
        self._animate()
        self._schedule_blink()

    # ------------------------------------------------------------------
    # API Pública
    # ------------------------------------------------------------------

    def set_expression(self, expression: str, transition_ms: int = 300) -> None:
        """Transiciona suavemente a una nueva expresión.

        Args:
            expression: neutral, feliz, triste, sorprendido, enojado,
                       escuchando, hablando.
            transition_ms: Duración de la transición (no usado directamente,
                          la interpolación es per-frame).
        """
        self._current_expression = expression
        self._is_pulsing = expression in ("escuchando", "hablando")
        target = self._expression_params(expression)
        self._target_params.update(target)

    def set_brightness(self, level: float) -> None:
        """Ajusta el brillo de los ojos (0.0 a 1.0).

        Configuración sensorial para evitar hipersensibilidad visual.
        """
        self._brightness = max(0.0, min(1.0, level))

    def get_expression(self) -> str:
        """Retorna la expresión actual."""
        return self._current_expression

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
        self._interpolate_params()

        # Actualizar fase de pulso para "escuchando"
        if self._is_pulsing:
            self._pulse_phase += 0.08
        else:
            self._pulse_phase = 0.0

        self._draw_eyes()
        self.canvas.after(33, self._animate)  # ~30fps

    def _schedule_blink(self) -> None:
        """Programa un parpadeo natural aleatorio."""
        if self._is_blinking:
            return
        # Parpadeo cada 3-6 segundos (rango natural)
        delay_ms = random.randint(3000, 6000)
        self.canvas.after(delay_ms, self._do_blink)

    def _do_blink(self) -> None:
        """Ejecuta un parpadeo suave."""
        self._is_blinking = True
        self._blink_close(step=0)

    def _blink_close(self, step: int) -> None:
        """Cierra los ojos gradualmente."""
        if step < 4:
            self._params["eye_open"] = max(0.05, self._params["eye_open"] - 0.25)
            self.canvas.after(25, lambda: self._blink_close(step + 1))
        else:
            self._blink_open(step=0)

    def _blink_open(self, step: int) -> None:
        """Abre los ojos gradualmente."""
        target_open = self._target_params.get("eye_open", 1.0)
        if step < 4:
            self._params["eye_open"] = min(
                target_open,
                self._params["eye_open"] + 0.25,
            )
            self.canvas.after(25, lambda: self._blink_open(step + 1))
        else:
            self._params["eye_open"] = target_open
            self._is_blinking = False
            self._schedule_blink()

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
