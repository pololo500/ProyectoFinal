"""Detección de pantalla gráfica vs arranque headless (SSH / peluche)."""
from __future__ import annotations

import os
import sys
from typing import Mapping

from pathlib import Path


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


def pick_default_devices(
    cameras: list[tuple[int, str]],
    microphones: list[tuple[int, str]],
    outputs: list[tuple[int, str]],
    skip_camera: bool = False,
) -> tuple[int, int | None, int | None]:
    """Primer dispositivo real de cada lista.

    ``skip_camera=True`` (headless): no abre OpenCV. En la Pi 5, VideoCapture(0)
    sobre libcamera suele terminar en Bus error; en headless los frames se tiran.
    Mic ``None`` = dispositivo por defecto de PortAudio (no el dummy -1).
    """
    cam = -1 if skip_camera else (cameras[0][0] if cameras else 0)
    real_mics = [(idx, name) for idx, name in microphones if idx >= 0]
    mic = real_mics[0][0] if real_mics else None
    out = outputs[0][0] if outputs else None
    return cam, mic, out
