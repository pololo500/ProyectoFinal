"""Catálogo de cuentos y canciones para skills silenciosos del LLM."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote_plus

from session_policy import _normalize, _phrase_key
from story_library import StoryLibrary, StoryRecord

MUSIC_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
CATALOG_TAGS = frozenset({"LIST_STORIES", "LIST_MUSIC"})


def _display_song_name(stem: str) -> str:
    return unquote_plus((stem or "").replace("_", " ")).strip()


def _catalog_key(text: str) -> str:
    decoded = unquote_plus((text or "").replace("_", " "))
    decoded = decoded.replace("-", " ")
    return _phrase_key(_normalize(decoded))


def list_story_titles(library: StoryLibrary) -> list[str]:
    return [rec.title for rec in library.list_stories()]


def resolve_story(library: StoryLibrary, query: str) -> StoryRecord | None:
    key = _phrase_key(_normalize(query))
    if not key:
        return None
    records = library.list_stories()
    for rec in records:
        if rec.id == query.strip() or _phrase_key(_normalize(rec.id)) == key:
            return rec
    for rec in records:
        title_key = _phrase_key(_normalize(rec.title))
        if key == title_key or key in title_key or title_key in key:
            return rec
    return None


def list_song_names(music_dir: Path) -> list[str]:
    root = Path(music_dir)
    if not root.exists():
        return []
    names: list[str] = []
    for path in sorted(root.iterdir()):
        if path.suffix.lower() in MUSIC_EXTS:
            names.append(_display_song_name(path.stem))
    return names


def resolve_song(music_dir: Path, query: str) -> Path | None:
    key = _catalog_key(query)
    if not key:
        return None
    root = Path(music_dir)
    if not root.exists():
        return None
    files = [p for p in sorted(root.iterdir()) if p.suffix.lower() in MUSIC_EXTS]
    for path in files:
        stem_key = _catalog_key(path.stem)
        if key == stem_key or key in stem_key or stem_key in key:
            return path
        if _catalog_key(path.name) == key:
            return path
    tokens = [t for t in key.split() if len(t) >= 4]
    if not tokens:
        return None
    best: Path | None = None
    best_hits = 0
    for path in files:
        stem_key = _catalog_key(path.stem)
        hits = sum(1 for t in tokens if t in stem_key)
        if hits > best_hits:
            best_hits = hits
            best = path
    return best if best_hits else None


def choose_song(music_dir: Path, query: str | None) -> Path | None:
    """Si hay nombre pedido, solo esa canción. Random únicamente sin query."""
    q = (query or "").strip()
    if q:
        return resolve_song(music_dir, q)
    root = Path(music_dir)
    if not root.exists():
        return None
    files = [p for p in sorted(root.iterdir()) if p.suffix.lower() in MUSIC_EXTS]
    if not files:
        return None
    import random

    return random.choice(files)


def catalog_followup_prompt(
    actions: list[dict[str, str]],
    *,
    stories: list[str],
    songs: list[str],
    child_text: str,
) -> str | None:
    names = {str(item.get("action") or "").upper() for item in actions}
    if not names & CATALOG_TAGS:
        return None
    parts: list[str] = []
    if "LIST_STORIES" in names:
        if stories:
            parts.append("Libros en la Pi: " + "; ".join(stories) + ".")
        else:
            parts.append("Libros en la Pi: ninguno. Pedile a mamá o papá que suban uno.")
    if "LIST_MUSIC" in names:
        if songs:
            parts.append("Canciones en la Pi: " + "; ".join(songs) + ".")
        else:
            parts.append("Canciones en la Pi: ninguna. Pedile a mamá o papá que suban una.")
    parts.append(f"El nene dijo: {child_text}")
    parts.append("Ofrecé solo de esa lista. No inventes títulos.")
    return " ".join(parts)
