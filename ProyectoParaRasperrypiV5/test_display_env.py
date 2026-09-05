"""Tests del arranque sin DISPLAY (SSH)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from display_env import has_gui_display, pick_default_devices, try_attach_local_display


class TestHasGuiDisplay(unittest.TestCase):
    def test_linux_sin_display_es_headless(self) -> None:
        env = {}
        with patch("display_env.sys.platform", "linux"):
            self.assertFalse(has_gui_display(env))

    def test_linux_con_display_tiene_gui(self) -> None:
        with patch("display_env.sys.platform", "linux"):
            self.assertTrue(has_gui_display({"DISPLAY": ":0"}))

    def test_windows_tiene_gui_sin_display(self) -> None:
        with patch("display_env.sys.platform", "win32"):
            self.assertTrue(has_gui_display({}))


class TestAttachLocalDisplay(unittest.TestCase):
    def test_sin_socket_x11_no_toca_env(self) -> None:
        env: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-existe"
            with patch("display_env.sys.platform", "linux"):
                self.assertFalse(try_attach_local_display(env, x11_socket=missing))
        self.assertNotIn("DISPLAY", env)

    def test_con_socket_x11_pone_display_0(self) -> None:
        env: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as tmp:
            socket = Path(tmp) / "X0"
            socket.write_bytes(b"")
            auth = Path(tmp) / ".Xauthority"
            auth.write_bytes(b"x")
            with patch("display_env.sys.platform", "linux"):
                self.assertTrue(
                    try_attach_local_display(env, x11_socket=socket, xauthority=auth)
                )
        self.assertEqual(env["DISPLAY"], ":0")
        self.assertEqual(env["XAUTHORITY"], str(auth))


class TestPickDefaultDevices(unittest.TestCase):
    def test_toma_el_primer_indice_de_cada_lista(self) -> None:
        cam, mic, out = pick_default_devices(
            [(2, "Cámara 2")],
            [(5, "5: USB mic")],
            [(7, "7: Speaker")],
        )
        self.assertEqual((cam, mic, out), (2, 5, 7))

    def test_sin_dispositivos_usa_fallbacks(self) -> None:
        cam, mic, out = pick_default_devices([], [], [])
        self.assertEqual(cam, 0)
        self.assertIsNone(mic)
        self.assertIsNone(out)

    def test_headless_no_abre_camara(self) -> None:
        cam, mic, out = pick_default_devices(
            [(0, "Cámara 0")],
            [(-1, "Sin micrófono")],
            [(0, "Parlante")],
            skip_camera=True,
        )
        self.assertEqual(cam, -1)
        self.assertIsNone(mic)
        self.assertEqual(out, 0)

    def test_ignora_mic_dummy_menos_uno(self) -> None:
        _, mic, _ = pick_default_devices(
            [(0, "Cámara 0")],
            [(-1, "Sin micrófono")],
            [],
        )
        self.assertIsNone(mic)


if __name__ == "__main__":
    unittest.main()
