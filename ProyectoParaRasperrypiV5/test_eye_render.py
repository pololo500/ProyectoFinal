"""Tests del renderer de ojos (Pillow) para la LCD ST7789."""
from __future__ import annotations

import unittest

from PIL import Image

from eye_render import EyeAnimator, image_to_rgb565


class TestEyeAnimator(unittest.TestCase):
    def test_render_landscape_para_lcd_2_4(self) -> None:
        animator = EyeAnimator()
        image = animator.render(320, 240)
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")

    def test_expresion_feliz_cambia_parametros(self) -> None:
        animator = EyeAnimator()
        before = dict(animator.params)
        animator.set_expression("feliz")
        self.assertEqual(animator.get_expression(), "feliz")
        self.assertNotEqual(animator.target_params["eye_curve"], before["eye_curve"])

    def test_pictograma_abrazo_se_guarda(self) -> None:
        animator = EyeAnimator()
        animator.set_pictogram("abrazo")
        self.assertEqual(animator.pictogram, "abrazo")

    def test_pensando_es_circulo_de_carga(self) -> None:
        animator = EyeAnimator()
        animator.set_expression("pensando")
        self.assertEqual(animator.get_expression(), "pensando")
        self.assertTrue(animator.is_pulsing)
        animator.pulse_phase = 2.0
        image = animator.render(320, 240)
        bg = (26, 26, 46)
        cx, cy = 160, 120
        ring = image.getpixel((cx + 50, cy))
        self.assertNotEqual(ring, bg)


class TestRgb565(unittest.TestCase):
    def test_rojo_puro_es_f800(self) -> None:
        image = Image.new("RGB", (1, 1), (255, 0, 0))
        payload = image_to_rgb565(image)
        self.assertEqual(payload, b"\xf8\x00")

    def test_tamano_es_dos_bytes_por_pixel(self) -> None:
        image = Image.new("RGB", (320, 240), (26, 26, 46))
        payload = image_to_rgb565(image)
        self.assertEqual(len(payload), 320 * 240 * 2)


if __name__ == "__main__":
    unittest.main()
