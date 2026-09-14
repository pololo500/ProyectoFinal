# Sprites PNG de ojos por emoción — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada emoción puede mostrar una grilla PNG 320×240 en la LCD/tkinter; si falta el par PNG+JSON, se siguen dibujando los ojos procedurales.

**Architecture:** `eye_sprites.py` carga `eyes/{emocion}.png` + `.json` a `SpriteClip`. `EyeAnimator` elige el frame en `render()`; `lcd.display` no cambia. Tkinter hace blit del mismo PIL cuando hay clip. `app.py` no se toca.

**Tech Stack:** Python 3.11, Pillow (ya en `requirements.txt`), `unittest`. Sin Cairo, sin SVG, sin dependencias nuevas.

## Global Constraints

- Celda fija 320×240 px; no va en el JSON.
- Un PNG + JSON por emoción en `ProyectoParaRasperrypiV5/eyes/`.
- Campos JSON: `columns` y `rows` enteros ≥ 1; `fps` número > 0; `loop` default `true`; `frame_count` default `columns * rows`, rango `1 .. columns * rows`.
- Frames izquierda → derecha, arriba → abajo. `index = floor(elapsed * fps)`; loop con `%`; si no, clamp al último.
- PNG con alpha se aplana sobre `(26, 26, 46)`.
- Un archivo malo omite esa emoción; la app no cae.
- Sin recarga en caliente. Sin cambios a `app.py`, intents, GPIO ni `lcd_panel.py`.
- Tests: `python -m unittest` desde `ProyectoParaRasperrypiV5`. Sin SPI ni PhotoImage en v1.
- No crear commits a menos que Teo lo pida. Si un paso dice Commit, omitirlo hasta que lo pida.

---

## File structure

- Create: `ProyectoParaRasperrypiV5/eye_sprites.py` — `CELL_WIDTH`, `CELL_HEIGHT`, `SpriteClip`, `default_eyes_dir()`, `load_bank()`.
- Create: `ProyectoParaRasperrypiV5/test_eye_sprites.py` — recorte, JSON, `frame_at`, errores.
- Create: `ProyectoParaRasperrypiV5/eyes/.gitkeep` — carpeta de arte vacía.
- Modify: `ProyectoParaRasperrypiV5/eye_render.py` — `EyeAnimator(sprites_dir=None)`, `has_sprite()`, `render()` con clip.
- Modify: `ProyectoParaRasperrypiV5/test_eye_render.py` — sprite vs procedural, reset, brillo, escala, pictograma, sin parpadeo.
- Modify: `ProyectoParaRasperrypiV5/eye_display.py` — canvas blit del PIL si `has_sprite()`.
- Do not modify: `app.py`, `workers.py`, `lcd_panel.py`, `hardware.py`.

---

### Task 1: SpriteClip.frame_at

**Files:**
- Create: `ProyectoParaRasperrypiV5/test_eye_sprites.py`
- Create: `ProyectoParaRasperrypiV5/eye_sprites.py`

**Interfaces:**
- Consumes: Pillow `Image`.
- Produces: `CELL_WIDTH = 320`, `CELL_HEIGHT = 240`. `class SpriteClip` con `frames: list[Image.Image]`, `fps: float`, `loop: bool`, `frame_count: int`, `frame_at(elapsed_s: float) -> Image.Image`.

- [ ] **Step 1: Write the failing test**

Crear `ProyectoParaRasperrypiV5/test_eye_sprites.py`:

```python
"""Tests de spritesheets PNG de ojos."""
from __future__ import annotations

import unittest

from PIL import Image

from eye_sprites import SpriteClip


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `ProyectoParaRasperrypiV5`):

```bash
python -m unittest test_eye_sprites.py -v
```

Expected: FAIL con `ModuleNotFoundError: No module named 'eye_sprites'` o `ImportError` de `SpriteClip`.

- [ ] **Step 3: Write minimal implementation**

Crear `ProyectoParaRasperrypiV5/eye_sprites.py`:

```python
"""Carga de spritesheets PNG por emoción (celdas 320×240)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from PIL import Image

CELL_WIDTH = 320
CELL_HEIGHT = 240


@dataclass
class SpriteClip:
    frames: list[Image.Image]
    fps: float
    loop: bool

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at(self, elapsed_s: float) -> Image.Image:
        count = self.frame_count
        if count <= 0:
            raise ValueError("SpriteClip sin frames")
        elapsed = max(0.0, float(elapsed_s))
        index = math.floor(elapsed * float(self.fps))
        if self.loop:
            index = index % count
        else:
            index = min(index, count - 1)
        return self.frames[index]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_eye_sprites.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit** (omitir si Teo no lo pidió)

```bash
git add ProyectoParaRasperrypiV5/eye_sprites.py ProyectoParaRasperrypiV5/test_eye_sprites.py
git commit -m "feat: SpriteClip avanza frames PNG por fps y loop"
```

---

### Task 2: load_bank (JSON + recorte + errores)

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_eye_sprites.py`
- Modify: `ProyectoParaRasperrypiV5/eye_sprites.py`

**Interfaces:**
- Consumes: `SpriteClip`, `CELL_WIDTH`, `CELL_HEIGHT`.
- Produces: `default_eyes_dir() -> Path` (`<dir de eye_sprites.py>/eyes`). `load_bank(directory: Path | str | None = None) -> dict[str, SpriteClip]`. Si `directory` es `None`, usa `default_eyes_dir()`. Si la carpeta no existe, `{}`. Stem = nombre del JSON sin extensión; hace falta el PNG par. Clips inválidos se omiten.

- [ ] **Step 1: Write the failing tests**

Agregar al final de `test_eye_sprites.py` (antes de `if __name__`), imports extra arriba (`json`, `tempfile`, `Path`) y esta clase:

```python
import json
import tempfile
from pathlib import Path

from eye_sprites import CELL_HEIGHT, CELL_WIDTH, load_bank


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
            self.assertEqual(load_bank(folder), {})

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
```

En el header de `test_eye_sprites.py` dejar:

```python
from eye_sprites import CELL_HEIGHT, CELL_WIDTH, SpriteClip, load_bank
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_eye_sprites.py -v
```

Expected: FAIL con `ImportError: cannot import name 'load_bank'` (los 4 de Task 1 siguen pasando).

- [ ] **Step 3: Write minimal implementation**

Reemplazar `ProyectoParaRasperrypiV5/eye_sprites.py` por:

```python
"""Carga de spritesheets PNG por emoción (celdas 320×240)."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from debug_logger import log_action

CELL_WIDTH = 320
CELL_HEIGHT = 240
_BG = (26, 26, 46)


@dataclass
class SpriteClip:
    frames: list[Image.Image]
    fps: float
    loop: bool

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at(self, elapsed_s: float) -> Image.Image:
        count = self.frame_count
        if count <= 0:
            raise ValueError("SpriteClip sin frames")
        elapsed = max(0.0, float(elapsed_s))
        index = math.floor(elapsed * float(self.fps))
        if self.loop:
            index = index % count
        else:
            index = min(index, count - 1)
        return self.frames[index]


def default_eyes_dir() -> Path:
    return Path(__file__).resolve().parent / "eyes"


def load_bank(directory: Path | str | None = None) -> dict[str, SpriteClip]:
    folder = default_eyes_dir() if directory is None else Path(directory)
    if not folder.is_dir():
        return {}
    bank: dict[str, SpriteClip] = {}
    for json_path in sorted(folder.glob("*.json")):
        stem = json_path.stem
        clip = _load_clip(folder, stem)
        if clip is not None:
            bank[stem] = clip
            log_action("EYES", f"sprite {stem} {clip.frame_count} frames")
    return bank


def _load_clip(folder: Path, stem: str) -> SpriteClip | None:
    json_path = folder / f"{stem}.json"
    png_path = folder / f"{stem}.png"
    if not json_path.is_file() or not png_path.is_file():
        return None
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        columns = _positive_int(meta.get("columns"))
        rows = _positive_int(meta.get("rows"))
        fps = _positive_number(meta.get("fps"))
        loop = meta.get("loop", True)
        if not isinstance(loop, bool):
            return None
        expected = columns * rows
        frame_count = meta.get("frame_count", expected)
        frame_count = _positive_int(frame_count)
        if frame_count > expected:
            return None
        sheet = Image.open(png_path)
        sheet.load()
        expected_size = (columns * CELL_WIDTH, rows * CELL_HEIGHT)
        if sheet.size != expected_size:
            return None
        rgb = _flatten_rgb(sheet)
        frames: list[Image.Image] = []
        for row in range(rows):
            for col in range(columns):
                if len(frames) >= frame_count:
                    break
                box = (
                    col * CELL_WIDTH,
                    row * CELL_HEIGHT,
                    (col + 1) * CELL_WIDTH,
                    (row + 1) * CELL_HEIGHT,
                )
                frames.append(rgb.crop(box).copy())
            if len(frames) >= frame_count:
                break
        if not frames:
            return None
        return SpriteClip(frames=frames, fps=float(fps), loop=loop)
    except Exception as exc:
        log_action("EYES", f"sprite {stem} omitido: {exc}")
        return None


def _flatten_rgb(sheet: Image.Image) -> Image.Image:
    if sheet.mode == "RGB":
        return sheet
    rgba = sheet.convert("RGBA")
    base = Image.new("RGBA", rgba.size, (*_BG, 255))
    base.alpha_composite(rgba)
    return base.convert("RGB")


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("entero inválido")
    if value < 1:
        raise ValueError("entero < 1")
    return value


def _positive_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("fps inválido")
    number = float(value)
    if number <= 0:
        raise ValueError("fps <= 0")
    return number
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_eye_sprites.py -v
```

Expected: PASS (todos los tests del archivo).

- [ ] **Step 5: Commit** (omitir si Teo no lo pidió)

```bash
git add ProyectoParaRasperrypiV5/eye_sprites.py ProyectoParaRasperrypiV5/test_eye_sprites.py
git commit -m "feat: cargar grilla PNG+JSON de ojos con fallback por archivo"
```

---

### Task 3: EyeAnimator usa el banco

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_eye_render.py`
- Modify: `ProyectoParaRasperrypiV5/eye_render.py`

**Interfaces:**
- Consumes: `load_bank(directory) -> dict[str, SpriteClip]`, `SpriteClip.frame_at(elapsed_s: float) -> Image.Image`.
- Produces: `EyeAnimator(sprites_dir: Path | str | None = None)`. `has_sprite(expression: str | None = None) -> bool`. `set_expression` pone `_clip_started_at = time.monotonic()`. `render(width, height)` si hay clip devuelve `frame_at(now - _clip_started_at)` en RGB 320×240 (brillo, fill y pictograma en Task 4). `_tick_blink` retorna si `has_sprite()`. Sin clip, `_draw` igual que hoy.

- [ ] **Step 1: Write the failing tests**

Agregar a `test_eye_render.py` (imports `json`, `tempfile`, `Path`; helper igual al de Task 2, copiado aquí porque este archivo se puede leer solo):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_eye_render.py -v
```

Expected: FAIL con `TypeError: EyeAnimator.__init__() got an unexpected keyword argument 'sprites_dir'` o `AttributeError: has_sprite`.

- [ ] **Step 3: Write minimal implementation**

En `eye_render.py`:

1. Imports: `from pathlib import Path` y `from eye_sprites import load_bank`.
2. Reemplazar `EyeAnimator.__init__` y `set_expression`, agregar `has_sprite`, ramificar `render` y `_tick_blink`:

```python
    def __init__(self, sprites_dir: Path | str | None = None) -> None:
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
        self._bank = load_bank(sprites_dir)
        self._clip_started_at: float = time.monotonic()

    def has_sprite(self, expression: str | None = None) -> bool:
        name = self.expression if expression is None else expression
        return name in self._bank

    def set_expression(self, expression: str, transition_ms: int = 300) -> None:
        del transition_ms
        self.expression = expression
        self.is_pulsing = expression in ("escuchando", "hablando", "pensando", "zzz")
        if expression in ("dormido", "zzz") or self.has_sprite():
            self._blink_mode = "idle"
        self.target_params.update(_expression_params(expression))
        self._clip_started_at = time.monotonic()

    def _tick_blink(self, now: float) -> None:
        if self.has_sprite() or self.expression in ("dormido", "pensando", "zzz"):
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
        clip = self._bank.get(self.expression)
        if clip is not None:
            elapsed = time.monotonic() - self._clip_started_at
            return clip.frame_at(elapsed).convert("RGB")
        image = Image.new("RGB", (max(1, width), max(1, height)), _BG)
        draw = ImageDraw.Draw(image)
        self._draw(draw, width, height)
        return image
```

Dejar el resto de `EyeAnimator` igual (`tick`, `_draw`, etc.).

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_eye_render.py test_eye_sprites.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit** (omitir si Teo no lo pidió)

```bash
git add ProyectoParaRasperrypiV5/eye_render.py ProyectoParaRasperrypiV5/test_eye_render.py
git commit -m "feat: EyeAnimator muestra sprites PNG cuando hay clip"
```

---

### Task 4: Brillo, fill y pictograma sobre el sprite

**Files:**
- Modify: `ProyectoParaRasperrypiV5/test_eye_render.py`
- Modify: `ProyectoParaRasperrypiV5/eye_render.py`

**Interfaces:**
- Consumes: `EyeAnimator.render`, `set_brightness`, `set_pictogram`, `_PICTOGRAM_LABELS`, `_pictogram_font`, `_scale_rgb`, `_HIGHLIGHT`.
- Produces: `render()` con clip aplica `pixel * brightness` (0..1), escala nearest **fill** al `width×height` pedido, y dibuja el pictograma igual que `_draw` (centro, `cy + min(h * 0.38, 160)`, `anchor="mm"`).

- [ ] **Step 1: Write the failing tests**

Agregar a `TestEyeAnimatorSprites` en `test_eye_render.py`:

```python
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
            self.assertNotEqual(list(before.getdata()), list(after.getdata()))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m unittest test_eye_render.py.TestEyeAnimatorSprites.test_brillo_multiplica_rgb_del_sprite -v
```

Expected: FAIL (`(255, 0, 0) != (127, 0, 0)`) si Task 3 aún no aplica brillo. Si el resize ya existe, el de brillo es el que debe fallar primero.

- [ ] **Step 3: Write minimal implementation**

En `eye_render.py`, reemplazar `render` y extraer helpers de sprite:

```python
    def render(self, width: int, height: int) -> Image.Image:
        clip = self._bank.get(self.expression)
        if clip is not None:
            elapsed = time.monotonic() - self._clip_started_at
            frame = clip.frame_at(elapsed)
            image = _sprite_to_canvas(frame, max(1, width), max(1, height), self.brightness)
            if self.pictogram:
                draw = ImageDraw.Draw(image)
                self._draw_pictogram(draw, width, height)
            return image
        image = Image.new("RGB", (max(1, width), max(1, height)), _BG)
        draw = ImageDraw.Draw(image)
        self._draw(draw, width, height)
        return image

    def _draw_pictogram(self, draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
        if not self.pictogram:
            return
        label = _PICTOGRAM_LABELS.get(self.pictogram, self.pictogram.upper())
        color = _scale_rgb(_HIGHLIGHT, self.brightness)
        cx = w / 2
        cy = h / 2
        y = cy + min(h * 0.38, 160)
        font = _pictogram_font(max(12, int(h * 0.08)))
        draw.text((cx, y), label, fill=color, font=font, anchor="mm")
```

En `_draw`, reemplazar el bloque final del pictograma por `self._draw_pictogram(draw, w, h)` (después del loop de ojos; `zzz`/`pensando` no llaman `_draw_pictogram` salvo que se setee pictograma en esas expresiones — `_draw` de ojos sí). El bloque a reemplazar es:

```python
        if self.pictogram:
            label = _PICTOGRAM_LABELS.get(self.pictogram, self.pictogram.upper())
            color = _scale_rgb(_HIGHLIGHT, self.brightness)
            y = cy + min(h * 0.38, 160)
            font = _pictogram_font(max(12, int(h * 0.08)))
            draw.text((cx, y), label, fill=color, font=font, anchor="mm")
```

por:

```python
        self._draw_pictogram(draw, w, h)
```

Agregar funciones a nivel de módulo (debajo de `_scale_rgb`):

```python
def _sprite_to_canvas(
    frame: Image.Image,
    width: int,
    height: int,
    brightness: float,
) -> Image.Image:
    image = frame.convert("RGB")
    if image.size != (width, height):
        try:
            resample = Image.Resampling.NEAREST
        except AttributeError:
            resample = Image.NEAREST
        image = image.resize((width, height), resample)
    level = max(0.0, min(1.0, brightness))
    if level < 1.0:
        image = image.point(lambda channel: int(channel * level))
    return image
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m unittest test_eye_render.py test_eye_sprites.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit** (omitir si Teo no lo pidió)

```bash
git add ProyectoParaRasperrypiV5/eye_render.py ProyectoParaRasperrypiV5/test_eye_render.py
git commit -m "feat: brillo, escala y pictograma sobre sprites de ojos"
```

---

### Task 5: Tkinter blit + carpeta eyes/

**Files:**
- Create: `ProyectoParaRasperrypiV5/eyes/.gitkeep`
- Modify: `ProyectoParaRasperrypiV5/eye_display.py` (`_animate`, nuevo `_blit_sprite_canvas`)
- Modify: `ProyectoParaRasperrypiV5/test_eye_render.py` (un test de `has_sprite` ya cubre el branch; no hay test PhotoImage)

**Interfaces:**
- Consumes: `EyeAnimator.has_sprite() -> bool`, `EyeAnimator.render(width, height) -> Image.Image`.
- Produces: si `canvas` no es `None` y `has_sprite()`, `_blit_sprite_canvas()` (PIL → `ImageTk.PhotoImage`, `create_image` en `0,0` `anchor="nw"`, referencia en `self._tk_photo`). Si no, `_draw_eyes()` actual. LCD sigue en `_blit_lcd` → `render()`.

- [ ] **Step 1: Write the failing test**

No hay test de PhotoImage (spec v1). Verificar que `has_sprite` sigue True (regresión) ejecutando los tests actuales. El cambio de canvas se valida por inspección + tests de `render`.

Agregar este test a `TestEyeAnimatorSprites` para documentar el contrato que usa `EyeDisplay`:

```python
    def test_has_sprite_false_si_otra_emocion_no_tiene_png(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            _write_sheet(folder, "feliz", [(255, 0, 0), (0, 255, 0)])
            animator = EyeAnimator(sprites_dir=folder)
            animator.set_expression("feliz")
            self.assertTrue(animator.has_sprite())
            animator.set_expression("zzz")
            self.assertFalse(animator.has_sprite())
```

- [ ] **Step 2: Run test to verify it fails**

Este test debería **pasar ya** tras Task 3. Si pasa, no reescribir `has_sprite`. El trabajo nuevo es el blit de canvas (sin test GUI).

```bash
python -m unittest test_eye_render.py.TestEyeAnimatorSprites.test_has_sprite_false_si_otra_emocion_no_tiene_png -v
```

Expected: PASS.

- [ ] **Step 3: Write the canvas blit**

En `EyeDisplay.__init__`, después de `self._pictogram = self._anim.pictogram`:

```python
        self._tk_photo = None
```

Reemplazar `_animate`:

```python
    def _animate(self) -> None:
        """Loop principal de animación (~30fps)."""
        self._anim.tick()
        self._sync_from_animator()
        if self.canvas is not None:
            if self._anim.has_sprite():
                self._blit_sprite_canvas()
            else:
                self._draw_eyes()
        self._blit_lcd()
        if self.canvas is not None:
            self.canvas.after(33, self._animate)
```

Agregar método (junto a `_blit_lcd`):

```python
    def _blit_sprite_canvas(self) -> None:
        if self.canvas is None:
            return
        from PIL import ImageTk

        frame = self._anim.render(max(1, self.width), max(1, self.height))
        self._tk_photo = ImageTk.PhotoImage(image=frame)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._tk_photo, anchor="nw")
```

Crear `ProyectoParaRasperrypiV5/eyes/.gitkeep` vacío (como `stories/.gitkeep`).

- [ ] **Step 4: Run tests**

```bash
python -m unittest test_eye_render.py test_eye_sprites.py -v
```

Expected: PASS. `EyeDisplay(None)` (headless) no importa `ImageTk`.

- [ ] **Step 5: Commit** (omitir si Teo no lo pidió)

```bash
git add ProyectoParaRasperrypiV5/eye_display.py ProyectoParaRasperrypiV5/eyes/.gitkeep ProyectoParaRasperrypiV5/test_eye_render.py
git commit -m "feat: mostrar sprites de ojos en el canvas tkinter"
```

---

## Verificación final

```bash
cd ProyectoParaRasperrypiV5
python -m unittest test_eye_render.py test_eye_sprites.py -v
```

Sin PNG en `eyes/`, arrancar la app (GUI o headless) debe verse como antes. Con `eyes/feliz.png` + `feliz.json` válidos, `set_expression("feliz")` anima el sheet en LCD y en tkinter.
