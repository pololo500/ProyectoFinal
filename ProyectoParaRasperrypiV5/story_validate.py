"""Heurística local para decidir si un texto es un cuento publicable para chicos."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MIN_WORDS = 80
MIN_SENTENCES = 3
MAX_DIGIT_RATIO = 0.18

_NARRATIVE_HINTS = (
    "habia una vez",
    "había una vez",
    "dijo",
    "pregunto",
    "preguntó",
    "capitulo",
    "capítulo",
    "entonces",
    "de pronto",
    "un dia",
    "un día",
)

_DOCUMENT_HINTS = (
    "total a pagar",
    "factura",
    "cuit",
    "http://",
    "https://",
    "copyright",
    "iva",
    "pagina 1 de",
    "página 1 de",
)

# Groserías / adulto. El motivo al padre no cita la palabra.
_BLOCKLIST = (
    "pornografia",
    "pornografía",
    "pornografia",
    "porno",
    "xxx",
    "nudes",
    "violacion",
    "violación",
    "violar",
    "asesinato",
    "gore",
    "suicidio",
    "masturb",
    "orgasmo",
    "pedofil",
    "pedófil",
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = ""


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", text))


def _sentence_count(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if len(p.strip()) > 8)


def validate_children_story(text: str) -> ValidationResult:
    cleaned = (text or "").strip()
    if not cleaned:
        return ValidationResult(False, "Este PDF no tiene texto para leer; subí uno que no sea foto de páginas.")

    words = _word_count(cleaned)
    if words < MIN_WORDS:
        return ValidationResult(False, "El texto es demasiado corto para un cuento.")
    if _sentence_count(cleaned) < MIN_SENTENCES:
        return ValidationResult(False, "No parece un cuento: hay muy pocas oraciones.")

    folded = _fold(cleaned)
    for banned in _BLOCKLIST:
        if _fold(banned) in folded:
            return ValidationResult(False, "El texto no parece adecuado para chicos.")

    digits = sum(ch.isdigit() for ch in cleaned)
    if digits / max(len(cleaned), 1) > MAX_DIGIT_RATIO:
        return ValidationResult(False, "Parece un documento con muchos números, no un cuento.")

    doc_hits = sum(1 for hint in _DOCUMENT_HINTS if hint in folded)
    narr_hits = sum(1 for hint in _NARRATIVE_HINTS if _fold(hint) in folded)
    if doc_hits >= 3 and narr_hits == 0:
        return ValidationResult(False, "Parece una factura o un manual, no un cuento.")

    return ValidationResult(True, "")


def clean_extracted_text(raw: str) -> str:
    lines: list[str] = []
    seen_headers: dict[str, int] = {}
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.fullmatch(r"\d{1,4}", stripped):
            continue
        key = stripped.lower()
        seen_headers[key] = seen_headers.get(key, 0) + 1
        lines.append(stripped)
    filtered: list[str] = []
    for line in lines:
        if line and seen_headers.get(line.lower(), 0) >= 4 and len(line) < 80:
            continue
        filtered.append(line)
    text = "\n".join(filtered)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def title_from_filename_and_text(filename: str, text: str) -> str:
    stem = PathStem(filename)
    first = ""
    for line in text.splitlines():
        if line.strip():
            first = line.strip()
            break
    if first and len(first) <= 80 and not first.endswith("."):
        return first
    return stem or "Cuento"


def PathStem(filename: str) -> str:
    name = filename.replace("\\", "/").split("/")[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.replace("_", " ").strip()


def split_for_speech(text: str, max_chars: int = 420) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if not paras:
        paras = [text.strip()] if text.strip() else []
    chunks: list[str] = []
    for para in paras:
        if len(para) <= max_chars:
            chunks.append(para)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        buf: list[str] = []
        for sentence in sentences:
            trial = " ".join(buf + [sentence]).strip()
            if buf and len(trial) > max_chars:
                chunks.append(" ".join(buf))
                buf = [sentence]
            else:
                buf.append(sentence)
        if buf:
            chunks.append(" ".join(buf).strip())
    return [c for c in chunks if c]
