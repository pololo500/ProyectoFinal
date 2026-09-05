"""Síntesis con Microsoft Elena Neural argentina (edge-tts)."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

VOICE_NAME = "es-AR-ElenaNeural"
VOICE_RATE = "-8%"

_WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*]')


def prepare_tts_text(text: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", text).strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?…":
        cleaned += "."
    return cleaned


def suggested_mp3_name(text: str) -> str:
    prepared = prepare_tts_text(text or "")
    slug = _WINDOWS_INVALID.sub("", prepared).strip().rstrip(".")
    slug = re.sub(r"\s{2,}", " ", slug).strip()
    if not slug:
        return "teo.mp3"
    if len(slug) > 40:
        slug = slug[:40].rstrip()
    return f"{slug}.mp3"


async def _synthesize_to_mp3(
    text: str,
    dest: Path,
    communicate_factory: Callable[..., Any] | None,
) -> Path:
    speech_text = prepare_tts_text(text or "")
    if not speech_text:
        raise ValueError("El texto está vacío")

    dest.parent.mkdir(parents=True, exist_ok=True)
    factory = communicate_factory
    if factory is None:
        import edge_tts

        factory = edge_tts.Communicate
    communicate = factory(speech_text, VOICE_NAME, rate=VOICE_RATE)
    await communicate.save(str(dest))
    return dest


def generate_mp3(
    text: str,
    dest: Path | str,
    *,
    communicate_factory: Callable[..., Any] | None = None,
) -> Path:
    return asyncio.run(_synthesize_to_mp3(text, Path(dest), communicate_factory))
