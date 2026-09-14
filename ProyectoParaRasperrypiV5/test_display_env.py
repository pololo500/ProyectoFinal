"""Tests del arranque sin DISPLAY (SSH)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from display_env import (
    PREFERRED_CAMERA_NEEDLES,
    PREFERRED_MIC_NEEDLES,
    PREFERRED_SPEAKER_NEEDLES,
    choose_ui_mode,
    has_gui_display,
    pick_default_devices,
    preferred_option_index,
    try_attach_local_display,
)


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

    def test_headless_puede_saltar_camara(self) -> None:
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

    def test_elige_usb_pnp_y_microii_por_nombre(self) -> None:
        cam, mic, out = pick_default_devices(
            [(0, "Cámara 0"), (1, "Cámara 1")],
            [
                (-1, "Sin micrófono"),
                (4, "4: vc4hdmi0: MAI PCM (hw:0,0)"),
                (1, "1: USB PnP Sound Device: Audio (hw:2,0)"),
            ],
            [
                (0, "0: vc4hdmi0: HDMI"),
                (2, "2: Audio Advantage MicroII: USB Audio (hw:3,0)"),
            ],
        )
        self.assertEqual(cam, 0)
        self.assertEqual(mic, 1)
        self.assertEqual(out, 2)

    def test_combo_preselecciona_microii(self) -> None:
        labels = [
            "0: vc4hdmi0: HDMI",
            "2: Audio Advantage MicroII: USB Audio (hw:3,0)",
        ]
        self.assertEqual(preferred_option_index(labels, PREFERRED_SPEAKER_NEEDLES), 1)
        self.assertEqual(preferred_option_index(labels, PREFERRED_MIC_NEEDLES), 0)

    def test_camara_10_no_es_camara_0(self) -> None:
        labels = ["Cámara 10", "Cámara 0"]
        self.assertEqual(preferred_option_index(labels, PREFERRED_CAMERA_NEEDLES), 1)


class TestChooseUiMode(unittest.TestCase):
    def test_sin_flags_es_headless(self) -> None:
        self.assertEqual(choose_ui_mode(debug=False, gui=False), "headless")

    def test_debug_gana(self) -> None:
        self.assertEqual(choose_ui_mode(debug=True, gui=True), "debug")

    def test_gui_fuerza_ventana(self) -> None:
        self.assertEqual(choose_ui_mode(debug=False, gui=True), "gui")


if __name__ == "__main__":
    unittest.main()
