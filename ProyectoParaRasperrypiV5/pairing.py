"""Token de pairing LAN entre la Pi y la app parental."""
from __future__ import annotations

import secrets
from pathlib import Path

TOKEN_PATH = Path(__file__).resolve().parent / "pairing_token.txt"


def load_or_create_token(path: Path | None = None) -> str:
    target = path or TOKEN_PATH
    if target.exists():
        token = target.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_hex(16)
    target.write_text(token + "\n", encoding="utf-8")
    return token
