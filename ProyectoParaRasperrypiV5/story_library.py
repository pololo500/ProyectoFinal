"""Persistencia de cuentos publicados (solo status ready)."""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from story_validate import (
    clean_extracted_text,
    title_from_filename_and_text,
    validate_children_story,
)

APP_DIR = Path(__file__).resolve().parent
DEFAULT_STORIES_DIR = APP_DIR / "stories"
MAX_PDF_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class StoryRecord:
    id: str
    title: str
    word_count: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "word_count": self.word_count,
            "created_at": self.created_at,
        }


def _slug(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title.lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return (folded[:40] or "cuento")


class StoryLibrary:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_STORIES_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def list_stories(self) -> list[StoryRecord]:
        records: list[StoryRecord] = []
        for meta_path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("status") not in (None, "ready"):
                continue
            txt = self.root / f"{meta_path.stem}.txt"
            if not txt.exists():
                continue
            records.append(
                StoryRecord(
                    id=str(data.get("id") or meta_path.stem),
                    title=str(data.get("title") or meta_path.stem),
                    word_count=int(data.get("word_count") or 0),
                    created_at=str(data.get("created_at") or ""),
                )
            )
        return records

    def save_story(self, title: str, text: str) -> StoryRecord:
        story_id = f"{_slug(title)}-{uuid.uuid4().hex[:6]}"
        created = datetime.now().isoformat(timespec="seconds")
        words = len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", text))
        tmp_txt = self.root / f".{story_id}.txt.tmp"
        tmp_json = self.root / f".{story_id}.json.tmp"
        tmp_txt.write_text(text, encoding="utf-8")
        payload = {
            "id": story_id,
            "title": title,
            "status": "ready",
            "word_count": words,
            "created_at": created,
        }
        tmp_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_txt.replace(self.root / f"{story_id}.txt")
        tmp_json.replace(self.root / f"{story_id}.json")
        return StoryRecord(story_id, title, words, created)

    def load_text(self, story_id: str) -> str | None:
        safe = Path(story_id).name
        path = self.root / f"{safe}.txt"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def get(self, story_id: str) -> StoryRecord | None:
        safe = Path(story_id).name
        meta = self.root / f"{safe}.json"
        txt = self.root / f"{safe}.txt"
        if not meta.exists() or not txt.exists():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return StoryRecord(
            id=str(data.get("id") or safe),
            title=str(data.get("title") or safe),
            word_count=int(data.get("word_count") or 0),
            created_at=str(data.get("created_at") or ""),
        )

    def delete(self, story_id: str) -> bool:
        safe = Path(story_id).name
        txt = self.root / f"{safe}.txt"
        meta = self.root / f"{safe}.json"
        existed = txt.exists() or meta.exists()
        if txt.exists():
            txt.unlink()
        if meta.exists():
            meta.unlink()
        return existed


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int, str | None]:
    """Devuelve (texto, páginas, error)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", 0, "Falta la librería pypdf en la Raspberry."
    import io

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return "", 0, "No pude abrir ese PDF."
    n_pages = len(reader.pages)
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = clean_extracted_text("\n".join(parts))
    if not text.strip():
        return "", n_pages, "Este PDF no tiene texto para leer; subí uno que no sea foto de páginas."
    return text, n_pages, None


def ingest_pdf(pdf_bytes: bytes, filename: str, stories_dir: Path | None = None) -> dict[str, Any]:
    lib = StoryLibrary(stories_dir)
    name = Path(filename).name
    if not name.lower().endswith(".pdf"):
        return {"status": "rejected", "reason": "Solo se aceptan archivos PDF."}
    if len(pdf_bytes) > MAX_PDF_BYTES:
        return {"status": "rejected", "reason": "El PDF pesa más de 8 MB."}
    if not pdf_bytes:
        return {"status": "rejected", "reason": "El archivo llegó vacío."}

    text, _pages, err = extract_pdf_text(pdf_bytes)
    if err:
        return {"status": "rejected", "reason": err}

    title = title_from_filename_and_text(name, text)
    check = validate_children_story(text)
    if not check.ok:
        return {"status": "rejected", "reason": check.reason}

    rec = lib.save_story(title, text)
    return {
        "status": "ready",
        "id": rec.id,
        "title": rec.title,
        "word_count": rec.word_count,
        "created_at": rec.created_at,
    }
