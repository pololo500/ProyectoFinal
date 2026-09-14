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
    hold_first_s: float = 0.0

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def frame_at(self, elapsed_s: float) -> Image.Image:
        count = self.frame_count
        if count <= 0:
            raise ValueError("SpriteClip sin frames")
        elapsed = max(0.0, float(elapsed_s))
        fps = float(self.fps)
        hold = max(0.0, float(self.hold_first_s))
        if hold <= 0.0 or count == 1:
            index = math.floor(elapsed * fps)
            if self.loop:
                index = index % count
            else:
                index = min(index, count - 1)
            return self.frames[index]
        rest = count - 1
        play_s = rest / fps
        cycle = hold + play_s
        t = (elapsed % cycle) if self.loop else elapsed
        if t < hold:
            return self.frames[0]
        index = 1 + math.floor((t - hold) * fps)
        return self.frames[min(index, count - 1)]


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


def _omit(stem: str, reason: str) -> None:
    log_action("EYES", f"sprite {stem} omitido: {reason}")


def _load_clip(folder: Path, stem: str) -> SpriteClip | None:
    json_path = folder / f"{stem}.json"
    png_path = folder / f"{stem}.png"
    if not json_path.is_file() or not png_path.is_file():
        _omit(stem, "falta png" if json_path.is_file() else "falta json")
        return None
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        columns = _positive_int(meta.get("columns"))
        rows = _positive_int(meta.get("rows"))
        fps = _positive_number(meta.get("fps"))
        loop = meta.get("loop", True)
        if not isinstance(loop, bool):
            _omit(stem, "loop no es bool")
            return None
        hold_first_s = float(meta.get("hold_first_s", 0) or 0)
        if isinstance(meta.get("hold_first_s", 0), bool) or hold_first_s < 0:
            _omit(stem, "hold_first_s inválido")
            return None
        expected = columns * rows
        frame_count = meta.get("frame_count", expected)
        frame_count = _positive_int(frame_count)
        if frame_count > expected:
            _omit(stem, f"frame_count {frame_count} > {expected}")
            return None
        sheet = Image.open(png_path)
        sheet.load()
        expected_size = (columns * CELL_WIDTH, rows * CELL_HEIGHT)
        if sheet.size != expected_size:
            _omit(stem, f"tamaño {sheet.size} != {expected_size}")
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
            _omit(stem, "sin frames")
            return None
        return SpriteClip(
            frames=frames,
            fps=float(fps),
            loop=loop,
            hold_first_s=hold_first_s,
        )
    except Exception as exc:
        _omit(stem, str(exc))
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
