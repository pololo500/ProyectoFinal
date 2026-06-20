"""vocabulary_tracker.py — Registro de desarrollo lingüístico del niño.

Mantiene un set de palabras únicas observadas en las transcripciones
(ya sanitizadas, sin PII).  Permite detectar avances o estancamientos
en el vocabulario.

Los datos se persisten en un archivo JSON local.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any


# Palabras funcionales que no cuentan como vocabulario significativo
_STOP_WORDS = frozenset({
    "a", "al", "con", "de", "del", "el", "en", "es", "la", "las", "lo",
    "los", "le", "les", "me", "mi", "no", "o", "por", "que", "se", "si",
    "su", "te", "un", "una", "y", "yo", "tu", "ya", "muy", "mas", "pero",
    "como", "para", "hay", "este", "esta", "esto", "ese", "esa", "eso",
    "ser", "ir", "ver", "dar", "ahi", "aca", "alla",
})


class VocabularyTracker:
    """Registra palabras únicas del niño a lo largo del tiempo.

    Attributes:
        known_words: Set de palabras normalizadas conocidas.
        history: Lista de eventos de descubrimiento ``(date, word)``.
    """

    def __init__(self, vocab_file: Path | None = None) -> None:
        if vocab_file is None:
            vocab_file = Path(__file__).resolve().parent / "vocabulary_data.json"
        self.vocab_file = vocab_file
        self.known_words: set[str] = set()
        self.history: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_transcript(self, sanitized_text: str) -> list[str]:
        """Tokeniza texto y retorna las palabras NUEVAS encontradas.

        Solo cuenta palabras de 2+ caracteres que no sean stop-words.
        """
        tokens = self._tokenize(sanitized_text)
        new_words: list[str] = []
        for token in tokens:
            if token not in self.known_words and token not in _STOP_WORDS and len(token) >= 2:
                self.known_words.add(token)
                new_words.append(token)
                self.history.append({
                    "word": token,
                    "date": date.today().isoformat(),
                    "timestamp": datetime.now().isoformat(),
                })
        if new_words:
            self._save()
        return new_words

    def get_stats(self) -> dict[str, Any]:
        """Retorna estadísticas del vocabulario."""
        today = date.today().isoformat()
        words_today = sum(1 for h in self.history if h.get("date") == today)
        return {
            "total_words": len(self.known_words),
            "new_words_today": words_today,
            "history_count": len(self.history),
        }

    def get_recent_words(self, limit: int = 20) -> list[str]:
        """Retorna las últimas N palabras descubiertas."""
        return [h["word"] for h in self.history[-limit:]]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        return normalized.lower().strip()

    def _tokenize(self, text: str) -> list[str]:
        normalized = self._normalize(text)
        return [t for t in re.findall(r"\w+", normalized) if t]

    def _load(self) -> None:
        if not self.vocab_file.exists():
            return
        try:
            data = json.loads(self.vocab_file.read_text(encoding="utf-8"))
            self.known_words = set(data.get("known_words", []))
            self.history = data.get("history", [])
        except Exception:
            pass

    def _save(self) -> None:
        data = {
            "known_words": sorted(self.known_words),
            "history": self.history,
            "stats": self.get_stats(),
        }
        try:
            self.vocab_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
