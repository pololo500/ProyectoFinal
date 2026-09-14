"""Detección de pantalla gráfica vs arranque headless (SSH / peluche)."""
from __future__ import annotations

import os
import re
import sys
from typing import Mapping

from pathlib import Path

PREFERRED_CAMERA_NEEDLES = ("cámara 0", "camara 0")
PREFERRED_MIC_NEEDLES = ("usb pnp sound device",)
PREFERRED_SPEAKER_NEEDLES = ("audio advantage microii", "microii")


def has_gui_display(env: Mapping[str, str] | None = None) -> bool:
    """True si hay DISPLAY/Wayland. En Windows tkinter no usa DISPLAY."""
    if sys.platform == "win32":
        return True
    current = os.environ if env is None else env
    return bool(current.get("DISPLAY") or current.get("WAYLAND_DISPLAY"))


def try_attach_local_display(
    env: dict[str, str] | None = None,
    x11_socket: Path | None = None,
    xauthority: Path | None = None,
) -> bool:
    """Si SSH no tiene DISPLAY pero hay escritorio en :0, úsalo."""
    current = os.environ if env is None else env
    if has_gui_display(current):
        return True
    socket = x11_socket if x11_socket is not None else Path("/tmp/.X11-unix/X0")
    if not socket.exists():
        return False
    current["DISPLAY"] = ":0"
    auth = xauthority if xauthority is not None else Path.home() / ".Xauthority"
    if auth.exists() and not current.get("XAUTHORITY"):
        current["XAUTHORITY"] = str(auth)
    return True


def choose_ui_mode(*, debug: bool, gui: bool) -> str:
    """debug → panel; gui → ojos HDMI; default → headless LCD."""
    if debug:
        return "debug"
    if gui:
        return "gui"
    return "headless"


def preferred_option_index(labels: list[str], needles: tuple[str, ...]) -> int:
    """Índice del primer label que matchea; 0 si ninguno."""
    for i, label in enumerate(labels):
        if _label_matches(label, needles):
            return i
    return 0


def _label_matches(label: str, needles: tuple[str, ...]) -> bool:
    folded = (label or "").lower()
    for needle in needles:
        if needle in ("cámara 0", "camara 0"):
            if re.search(r"c[aá]mara\s+0(?!\d)", folded):
                return True
            continue
        if needle in folded:
            return True
    return False


def pick_default_devices(
    cameras: list[tuple[int, str]],
    microphones: list[tuple[int, str]],
    outputs: list[tuple[int, str]],
    skip_camera: bool = False,
) -> tuple[int, int | None, int | None]:
    """Dispositivos preferidos del peluche; si no hay match, el primer real.

    ``skip_camera=True``: no abre OpenCV (índice -1).
    Mic ``None`` = dispositivo por defecto de PortAudio (no el dummy -1).
    """
    if skip_camera:
        cam = -1
    elif cameras:
        cam_i = preferred_option_index([name for _, name in cameras], PREFERRED_CAMERA_NEEDLES)
        cam = cameras[cam_i][0]
    else:
        cam = 0

    real_mics = [(idx, name) for idx, name in microphones if idx >= 0]
    if real_mics:
        mic_i = preferred_option_index([name for _, name in real_mics], PREFERRED_MIC_NEEDLES)
        mic: int | None = real_mics[mic_i][0]
    else:
        mic = None

    if outputs:
        out_i = preferred_option_index([name for _, name in outputs], PREFERRED_SPEAKER_NEEDLES)
        out: int | None = outputs[out_i][0]
    else:
        out = None
    return cam, mic, out
