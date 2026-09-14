"""Tests del renderer de ojos (Pillow) para la LCD ST7789."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from eye_render import EyeAnimator, image_to_rgb565
from eye_sprites import CELL_HEIGHT, CELL_WIDTH


_BG = (26, 26, 46)
_SCLERA = (224, 247, 250)


def _write_sheet(
    folder: Path,
    stem: str,
    colors: list[tuple[int, int, int]],
    *,
    columns: int = 2,
    rows: int = 1,
    fps: float = 10,
    loop: bool = True,
) -> None:
    sheet = Image.new("RGB", (columns * CELL_WIDTH, rows * CELL_HEIGHT), _BG)
    for index, color in enumerate(colors):
        row = index // columns
        col = index % columns
        cell = Image.new("RGB", (CELL_WIDTH, CELL_HEIGHT), color)
        sheet.paste(cell, (col * CELL_WIDTH, row * CELL_HEIGHT))
    sheet.save(folder / f"{stem}.png")
    (folder / f"{stem}.json").write_text(
        json.dumps({"columns": columns, "rows": rows, "fps": fps, "loop": loop}),
        encoding="utf-8",
    )


class TestEyeAnimator(unittest.TestCase):
    def test_render_landscape_para_lcd_2_4(self) -> None:
        animator = EyeAnimator(sprites_dir=tempfile.mkdtemp())
        image = animator.render(320, 240)
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")

    def test_expresion_feliz_cambia_parametros(self) -> None:
        animator = EyeAnimator(sprites_dir=tempfile.mkdtemp())
        before = dict(animator.params)
        animator.set_expression("feliz")
        self.assertEqual(animator.get_expression(), "feliz")
        self.assertNotEqual(animator.target_params["eye_curve"], before["eye_curve"])

    def test_pictograma_abrazo_se_guarda(self) -> None:
        animator = EyeAnimator(sprites_dir=tempfile.mkdtemp())
        animator.set_pictogram("abrazo")
        self.assertEqual(animator.pictogram, "abrazo")

    def test_pensando_es_circulo_de_carga(self) -> None:
        animator = EyeAnimator(sprites_dir=tempfile.mkdtemp())
        animator.set_expression("pensando")
        self.assertEqual(animator.get_expression(), "pensando")
        self.assertTrue(animator.is_pulsing)
        animator.pulse_phase = 2.0
        image = animator.render(320, 240)
        cx, cy = 160, 120
        ring = image.getpixel((cx + 50, cy))
        self.assertNotEqual(ring, _BG)

    def test_zzz_dibuja_texto_y_no_ojos(self) -> None:
        animator = EyeAnimator(sprites_dir=tempfile.mkdtemp())
        animator.set_expression("zzz")
        self.assertEqual(animator.get_expression(), "zzz")
        image = animator.render(320, 240)
        self.assertEqual(image.getpixel((112, 120)), _BG)
        self.assertNotEqual(image.getpixel((160, 120)), _BG)


class TestEyeAnimatorSprites(unittest.TestCase):
    def test_render_sprite_no_pinta_esclera(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            image = animator.render(320, 240)
            self.assertTrue(animator.has_sprite())
            self.assertEqual(image.getpixel((112, 120)), (255, 0, 0))
            self.assertNotEqual(image.getpixel((112, 120)), _SCLERA)

    def test_sin_archivos_sigue_neutral_procedural(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            animator = EyeAnimator(sprites_dir=raw)
            image = animator.render(320, 240)
            self.assertFalse(animator.has_sprite())
            self.assertNotEqual(image.getpixel((112, 120)), _BG)

    def test_json_roto_sigue_procedural(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            Image.new("RGB", (640, 240), (255, 0, 0)).save(folder / "feliz.png")
            (folder / "feliz.json").write_text("{", encoding="utf-8")
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            image = animator.render(320, 240)
            self.assertFalse(animator.has_sprite("feliz"))
            self.assertNotEqual(image.getpixel((112, 120)), (255, 0, 0))

    def test_cambiar_emocion_reinicia_frame_0(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            _write_sheet(folder, "triste", [(0, 0, 255), (255, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (255, 0, 0))
            animator.set_expression("triste")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (0, 0, 255))

    def test_sprite_no_parpadea_procedural(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "neutral", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("neutral")
            animator.params["eye_open"] = 1.0
            animator._next_blink_at = 0.0
            for _ in range(20):
                animator.tick()
            self.assertGreater(animator.params["eye_open"], 0.5)

    def test_brillo_multiplica_rgb_del_sprite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            animator.set_brightness(0.5)
            pixel = animator.render(320, 240).getpixel((0, 0))
            self.assertEqual(pixel, (127, 0, 0))

    def test_escala_nearest_llena_el_destino(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            image = animator.render(640, 480)
            self.assertEqual(image.size, (640, 480))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(image.getpixel((639, 479)), (255, 0, 0))

    def test_pictograma_se_dibuja_sobre_el_sprite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            before = animator.render(320, 240)
            animator.set_pictogram("abrazo")
            after = animator.render(320, 240)
            self.assertNotEqual(before.tobytes(), after.tobytes())

    def test_has_sprite_false_si_otra_emocion_no_tiene_png(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            self.assertTrue(animator.has_sprite())
            animator.set_expression("zzz")
            self.assertFalse(animator.has_sprite())

    def test_default_cubre_neutral_pero_no_zzz(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(
                folder,
                "Default",
                [(255, 0, 0), (0, 255, 0)],
                fps=15,
            )
            json_path = folder / "Default.json"
            meta = json.loads(json_path.read_text(encoding="utf-8"))
            meta["hold_first_s"] = 5
            json_path.write_text(json.dumps(meta), encoding="utf-8")
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("neutral")
            self.assertTrue(animator.has_sprite())
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (255, 0, 0))
            animator.set_expression("zzz")
            self.assertFalse(animator.has_sprite())

    def test_hablando_no_pisa_el_sprite_de_triste(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "triste", [(0, 0, 255), (0, 0, 200)])
            _write_sheet(folder, "Default", [(255, 0, 0), (200, 0, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("triste")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (0, 0, 255))
            animator.set_expression("hablando")
            self.assertEqual(animator.get_expression(), "triste")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (0, 0, 255))

    def test_neutral_no_pisa_triste_en_seguida(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "triste", [(0, 0, 255), (0, 0, 200)])
            _write_sheet(folder, "Default", [(255, 0, 0), (200, 0, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("triste")
            animator.set_expression("neutral")
            self.assertEqual(animator.get_expression(), "triste")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (0, 0, 255))

    def test_neutral_saca_los_ojos_de_dormido(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "dormido", [(0, 255, 0), (0, 200, 0)])
            _write_sheet(folder, "Default", [(255, 0, 0), (200, 0, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("dormido")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (0, 255, 0))
            animator.set_expression("neutral")
            self.assertEqual(animator.get_expression(), "neutral")
            self.assertEqual(animator.render(320, 240).getpixel((0, 0)), (255, 0, 0))


class TestEyeDisplayAnimate(unittest.TestCase):
    def test_canvas_blit_falla_lcd_y_loop_siguen(self) -> None:
        from eye_display import EyeDisplay

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            display = EyeDisplay(None, animator=animator)
            after_calls: list[tuple] = []

            class FakeCanvas:
                def after(self, ms, fn):
                    after_calls.append((ms, fn))

            class FakeLcd:
                def __init__(self) -> None:
                    self.display_width = 320
                    self.display_height = 240
                    self.frames: list = []

                def display(self, frame) -> None:
                    self.frames.append(frame)

            lcd = FakeLcd()
            display.canvas = FakeCanvas()
            display.lcd = lcd

            def boom() -> None:
                raise RuntimeError("PhotoImage")

            display._blit_sprite_canvas = boom  # type: ignore[method-assign]
            display._animate()
            self.assertEqual(len(lcd.frames), 1)
            self.assertEqual(after_calls[0][0], 33)


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
