"""Tests de spritesheets PNG de ojos."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from eye_sprites import CELL_HEIGHT, CELL_WIDTH, SpriteClip, load_bank


def _solid(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (320, 240), color)


class TestSpriteClipFrameAt(unittest.TestCase):
    def test_elapsed_cero_es_frame_0(self) -> None:
        clip = SpriteClip([_solid((255, 0, 0)), _solid((0, 255, 0))], fps=10.0, loop=True)
        self.assertEqual(clip.frame_count, 2)
        self.assertEqual(clip.frame_at(0.0).getpixel((0, 0)), (255, 0, 0))

    def test_elapsed_015_a_10fps_es_frame_1(self) -> None:
        clip = SpriteClip([_solid((255, 0, 0)), _solid((0, 255, 0))], fps=10.0, loop=True)
        self.assertEqual(clip.frame_at(0.15).getpixel((0, 0)), (0, 255, 0))

    def test_loop_vuelve_a_frame_0(self) -> None:
        clip = SpriteClip([_solid((255, 0, 0)), _solid((0, 255, 0))], fps=10.0, loop=True)
        self.assertEqual(clip.frame_at(0.20).getpixel((0, 0)), (255, 0, 0))

    def test_sin_loop_se_queda_en_el_ultimo(self) -> None:
        clip = SpriteClip([_solid((255, 0, 0)), _solid((0, 255, 0))], fps=10.0, loop=False)
        self.assertEqual(clip.frame_at(5.0).getpixel((0, 0)), (0, 255, 0))

    def test_hold_first_cinco_segundos_queda_en_frame_0(self) -> None:
        clip = SpriteClip(
            [_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))],
            fps=15.0,
            loop=True,
            hold_first_s=5.0,
        )
        self.assertEqual(clip.frame_at(0.0).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(clip.frame_at(4.99).getpixel((0, 0)), (255, 0, 0))

    def test_hold_first_luego_transiciona_a_15fps(self) -> None:
        clip = SpriteClip(
            [_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))],
            fps=15.0,
            loop=True,
            hold_first_s=5.0,
        )
        self.assertEqual(clip.frame_at(5.0).getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(clip.frame_at(5.0 + 1.5 / 15.0).getpixel((0, 0)), (0, 0, 255))

    def test_hold_first_loop_vuelve_a_frame_0(self) -> None:
        clip = SpriteClip(
            [_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))],
            fps=15.0,
            loop=True,
            hold_first_s=5.0,
        )
        cycle = 5.0 + 2.0 / 15.0
        self.assertEqual(clip.frame_at(cycle).getpixel((0, 0)), (255, 0, 0))


def _write_sheet(
    folder: Path,
    stem: str,
    colors: list[tuple[int, int, int]],
    *,
    columns: int = 2,
    rows: int = 1,
    fps: float = 10,
    loop: bool = True,
    frame_count: int | None = None,
    hold_first_s: float | None = None,
    mode: str = "RGB",
) -> None:
    sheet = Image.new(mode, (columns * CELL_WIDTH, rows * CELL_HEIGHT), (26, 26, 46, 255) if mode == "RGBA" else (26, 26, 46))
    for index, color in enumerate(colors):
        row = index // columns
        col = index % columns
        cell = Image.new(mode, (CELL_WIDTH, CELL_HEIGHT), color)
        sheet.paste(cell, (col * CELL_WIDTH, row * CELL_HEIGHT))
    sheet.save(folder / f"{stem}.png")
    meta: dict = {"columns": columns, "rows": rows, "fps": fps, "loop": loop}
    if frame_count is not None:
        meta["frame_count"] = frame_count
    if hold_first_s is not None:
        meta["hold_first_s"] = hold_first_s
    (folder / f"{stem}.json").write_text(json.dumps(meta), encoding="utf-8")


class TestLoadBank(unittest.TestCase):
    def test_recorta_dos_frames_320x240(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            bank = load_bank(folder)
            clip = bank["feliz"]
            self.assertEqual(clip.frame_count, 2)
            self.assertEqual(clip.frames[0].size, (320, 240))
            self.assertEqual(clip.frames[1].size, (320, 240))
            self.assertEqual(clip.frames[0].getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(clip.frames[1].getpixel((0, 0)), (0, 255, 0))

    def test_grilla_2x2_va_izquierda_derecha_arriba_abajo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(
                folder,
                "feliz",
                [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)],
                columns=2,
                rows=2,
            )
            clip = load_bank(folder)["feliz"]
            self.assertEqual(clip.frame_count, 4)
            self.assertEqual(clip.frames[2].getpixel((0, 0)), (0, 0, 255))

    def test_alpha_se_aplana_sobre_fondo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(
                folder,
                "feliz",
                [(255, 0, 0, 0), (0, 255, 0, 255)],
                mode="RGBA",
            )
            clip = load_bank(folder)["feliz"]
            self.assertEqual(clip.frames[0].mode, "RGB")
            self.assertEqual(clip.frames[0].getpixel((0, 0)), (26, 26, 46))

    def test_json_roto_se_omite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            Image.new("RGB", (640, 240), (255, 0, 0)).save(folder / "feliz.png")
            (folder / "feliz.json").write_text("{", encoding="utf-8")
            self.assertEqual(load_bank(folder), {})

    def test_png_tamano_incorrecto_se_omite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            Image.new("RGB", (100, 100), (255, 0, 0)).save(folder / "feliz.png")
            (folder / "feliz.json").write_text(
                json.dumps({"columns": 2, "rows": 1, "fps": 10}),
                encoding="utf-8",
            )
            with patch("eye_sprites.log_action") as logged:
                self.assertEqual(load_bank(folder), {})
            logged.assert_called()
            component, message = logged.call_args.args[:2]
            self.assertEqual(component, "EYES")
            self.assertIn("omitido", message)

    def test_sin_png_par_se_omite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / "feliz.json").write_text(
                json.dumps({"columns": 1, "rows": 1, "fps": 10}),
                encoding="utf-8",
            )
            self.assertEqual(load_bank(folder), {})

    def test_carpeta_inexistente_es_vacia(self) -> None:
        self.assertEqual(load_bank(Path("no/existe/eyes-xyz")), {})

    def test_frame_count_recorta_celdas(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(
                folder,
                "feliz",
                [(255, 0, 0), (0, 255, 0)],
                frame_count=1,
            )
            self.assertEqual(load_bank(folder)["feliz"].frame_count, 1)

    def test_un_malo_no_tira_el_bueno(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            (folder / "triste.json").write_text("{", encoding="utf-8")
            Image.new("RGB", (640, 240), (0, 0, 255)).save(folder / "triste.png")
            bank = load_bank(folder)
            self.assertIn("feliz", bank)
            self.assertNotIn("triste", bank)

    def test_hold_first_s_se_lee_del_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(
                folder,
                "Default",
                [(255, 0, 0), (0, 255, 0)],
                fps=15,
                hold_first_s=5,
            )
            clip = load_bank(folder)["Default"]
            self.assertEqual(clip.hold_first_s, 5)
            self.assertEqual(clip.fps, 15.0)
            self.assertEqual(clip.frame_at(4.0).getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(clip.frame_at(5.0).getpixel((0, 0)), (0, 255, 0))

    def test_archivo_default_real_carga_6_frames(self) -> None:
        from eye_sprites import default_eyes_dir

        clip = load_bank(default_eyes_dir())["Default"]
        self.assertEqual(clip.frame_count, 6)
        self.assertEqual(clip.fps, 15.0)
        self.assertEqual(clip.hold_first_s, 5.0)
        self.assertTrue(clip.loop)
        for frame in clip.frames:
            self.assertEqual(frame.size, (320, 240))


if __name__ == "__main__":
    unittest.main()
