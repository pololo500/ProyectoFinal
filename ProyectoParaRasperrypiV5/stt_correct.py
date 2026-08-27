"""Corrección y filtro post-Whisper para habla infantil en español."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence

_TOKEN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+|[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")

_GLUE = (
    (re.compile(r"papelotijera", re.IGNORECASE), "papel o tijera"),
    (re.compile(r"piedrapapel", re.IGNORECASE), "piedra papel"),
)

# Préstamos que un nene rioplatense sí dice; no se tiran aunque parezcan inglés.
_LOANWORDS = frozenset({
    "ok",
    "okay",
    "wifi",
    "yoga",
    "teo",
    "sandwich",
    "sandwiche",
    "video",
    "videos",
    "hobby",
})

# Inglés típico de alucinaciones de Whisper (no se usa en el habla del nene).
_ENGLISH_DROP = frozenset({
    "the", "this", "that", "with", "from", "have", "been", "were", "they",
    "them", "then", "than", "what", "when", "where", "which", "while",
    "will", "would", "could", "should", "about", "after", "before",
    "because", "really", "something", "anything", "everything", "nothing",
    "going", "watching", "subscribe", "thanks", "thank", "please", "hello",
    "english", "plunder", "pancake", "pancakes", "like", "share", "youtube",
    "captions", "subtitles", "copyright", "amara", "music", "song",
    "songs", "story", "stories", "play", "game", "games", "yes", "yeah",
    "hey", "wow", "cool", "fine", "good", "well", "just", "very", "also",
    "into", "over", "your", "youre", "dont", "cant", "isnt", "thats",
    "whats", "lets", "gonna", "wanna", "there", "their", "these", "those",
    "here", "come", "came", "know", "think", "want", "make", "made",
    "time", "back", "some", "more", "only", "other", "people", "little",
    "great", "right", "still", "even", "most", "take", "taken", "being",
    "doing", "looking", "listen", "listening", "watch", "thanks",
})

_ENGLISH_SHAPES = re.compile(
    r"(th|wh|ck|igh|ough|wr|kn|tion$|ness$|ing$|ly$)",
    re.IGNORECASE,
)

_VOWELS = set("aeiouáéíóúü")


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        current = [i]
        for j, rch in enumerate(right, start=1):
            ins = current[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (lch != rch)
            current.append(min(ins, delete, sub))
        prev = current
    return prev[-1]


def _best_extra_word(token: str, extra_words: Sequence[str]) -> str | None:
    folded = _fold(token)
    if len(folded) < 4 or not extra_words:
        return None
    best: str | None = None
    best_d = 99
    for word in extra_words:
        if abs(len(folded) - len(word)) > 2:
            continue
        distance = _levenshtein(folded, word)
        if distance >= best_d:
            continue
        max_d = 2 if len(folded) >= 4 else 1
        if 0 < distance <= max_d:
            best = word
            best_d = distance
    return best


def correct_stt_text(text: str, extra_words: Sequence[str] = ()) -> str:
    """Separa pegotes de juego y acerca tiguera→tijera solo con extra_words."""
    if not (text or "").strip():
        return text
    out = text
    for pattern, repl in _GLUE:
        out = pattern.sub(repl, out)
    if not extra_words:
        return out
    pieces: list[str] = []
    for token in _TOKEN.findall(out):
        if any(ch.isalpha() for ch in token):
            match = _best_extra_word(token, extra_words)
            pieces.append(match if match else token)
        else:
            pieces.append(token)
    return "".join(pieces)


def _has_spanish_mark(token: str) -> bool:
    return any(ch in token for ch in "áéíóúüñÁÉÍÓÚÜÑ")


def _looks_english(folded: str) -> bool:
    if folded in _LOANWORDS:
        return False
    if folded in _ENGLISH_DROP:
        return True
    if len(folded) >= 4 and _ENGLISH_SHAPES.search(folded) and not any(
        ch in folded for ch in "ñáéíóúü"
    ):
        # "cuando" no tiene th/ck; "watching" sí.
        return True
    return False


def _should_drop(token: str, is_known_spanish: Callable[[str], bool] | None) -> bool:
    folded = _fold(token)
    if not folded or folded.isdigit():
        return False
    if len(folded) <= 2:
        return False
    if folded in _LOANWORDS:
        return False
    if _has_spanish_mark(token):
        return False
    if _looks_english(folded):
        return True
    if is_known_spanish is None:
        return False
    if is_known_spanish(token):
        return False
    # Palabra inventada: no está en español y no es un nombre con acento.
    return len(folded) >= 4


def _tidy_spacing(text: str) -> str:
    out = re.sub(r"\s+", " ", text)
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"([¿¡])\s+", r"\1", out)
    out = re.sub(r"\s+([¿¡])", r" \1", out)
    return out.strip()


def filter_stt_tokens(
    text: str,
    is_known_spanish: Callable[[str], bool] | None = None,
) -> str:
    """Saca inglés y palabras inventadas; deja español corriente."""
    if not (text or "").strip():
        return text
    pieces: list[str] = []
    for token in _TOKEN.findall(text):
        if any(ch.isalpha() for ch in token) and _should_drop(token, is_known_spanish):
            continue
        pieces.append(token)
    return _tidy_spacing("".join(pieces))


def polish_stt_text(
    text: str,
    extra_words: Sequence[str] = (),
    is_known_spanish: Callable[[str], bool] | None = None,
) -> str:
    """Pipeline STT: pegotes/juego y después filtro de vocabulario."""
    return filter_stt_tokens(
        correct_stt_text(text, extra_words=extra_words),
        is_known_spanish=is_known_spanish,
    )


def spanish_vocab_checker(nlp: object | None) -> Callable[[str], bool] | None:
    """Usa vectores de spaCy (es_core_news_md). None si el modelo es blank."""
    if nlp is None:
        return None
    vocab = getattr(nlp, "vocab", None)
    if vocab is None:
        return None
    try:
        if not vocab["hola"].has_vector:
            return None
    except Exception:
        return None

    def known(word: str) -> bool:
        folded = _fold(word)
        if not folded:
            return False
        try:
            return bool(vocab[folded].has_vector)
        except Exception:
            return False

    return known
