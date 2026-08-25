"""Motor de cuentos multi-turno: listar, elegir, devolver párrafos para TTS."""
from __future__ import annotations

import random
import re
import unicodedata
from typing import Any

from story_library import StoryLibrary, StoryRecord
from story_validate import split_for_speech


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _wants_exit(text: str) -> bool:
    folded = _fold(text)
    phrases = ("no quiero", "no quiero mas", "me aburro", "me aburri")
    if any(p in folded for p in phrases):
        return True
    words = set(re.findall(r"\w+", folded))
    return bool(words & {"basta", "salir", "parar", "chau", "despues", "después"})


def _wants_accept(text: str) -> bool:
    folded = _fold(text)
    if any(p in folded for p in ("cualquiera", "el que quieras", "uno cualquiera", "el que sea")):
        return True
    words = set(re.findall(r"\w+", folded))
    return bool(words & {"si", "sí", "dale", "bueno", "ese", "esa", "leelo", "lee", "ok"})


def _wants_another(text: str) -> bool:
    folded = _fold(text)
    if "cuento" in folded:
        return True
    words = set(re.findall(r"\w+", folded))
    return bool(words & {"otro", "si", "sí", "dale"})


def _match_title(text: str, stories: list[StoryRecord]) -> StoryRecord | None:
    folded = _fold(text)
    tokens = [t for t in re.findall(r"\w+", folded) if len(t) >= 3]
    if not tokens:
        return None
    hits: list[StoryRecord] = []
    for rec in stories:
        title_tokens = set(t for t in re.findall(r"\w+", _fold(rec.title)) if len(t) >= 3)
        if title_tokens & set(tokens):
            hits.append(rec)
    if len(hits) == 1:
        return hits[0]
    return None


class StoryEngine:
    def __init__(self, library: StoryLibrary | None = None) -> None:
        self._library = library or StoryLibrary()
        self._state = "idle"
        self._pending_id: str | None = None
        self._offer_retries = 0

    @property
    def is_active(self) -> bool:
        return self._state in ("offering", "awaiting_more")

    def cancel(self) -> None:
        self._state = "idle"
        self._pending_id = None
        self._offer_retries = 0

    def process_or_passthrough(
        self,
        text: str,
        dispatcher_result: dict[str, Any],
    ) -> dict[str, Any]:
        if self.is_active:
            return self._handle_turn(text)
        if dispatcher_result.get("intent_name") == "story_request":
            return self._begin_offer()
        return dispatcher_result

    def _begin_offer(self) -> dict[str, Any]:
        stories = self._library.list_stories()
        if not stories:
            self.cancel()
            return self._payload(
                "story_request",
                "Pedile a mamá o papá que te suban un cuento desde el celular.",
            )
        self._state = "offering"
        self._offer_retries = 0
        if len(stories) == 1:
            self._pending_id = stories[0].id
            return self._payload(
                "story_request",
                f"Tengo {stories[0].title}. ¿Te lo leo?",
            )
        self._pending_id = None
        names = self._join_titles(stories)
        return self._payload(
            "story_request",
            f"Tengo {names}. ¿Cuál querés, o cualquiera?",
        )

    def _handle_turn(self, text: str) -> dict[str, Any]:
        if self._state == "awaiting_more":
            folded = _fold(text)
            no_more = folded.strip() in {"no", "no gracias"} or (
                _wants_exit(text) and "cuento" not in folded
            )
            if no_more:
                self.cancel()
                return self._payload("story_request", "Listo, paramos. Cuando quieras otro cuento, pedímelo.")
            if _wants_another(text):
                return self._begin_offer()
            self.cancel()
            return self._payload("story_request", "Bueno, después seguimos.")

        # offering
        if _wants_exit(text):
            self.cancel()
            return self._payload("story_request", "Bueno, después lo leemos.")

        if self._pending_id and _wants_accept(text):
            rec = self._library.get(self._pending_id)
            if rec is None:
                self.cancel()
                return self._payload("story_request", "Ese ya no está.")
            return self._start_reading(rec)

        stories = self._library.list_stories()
        if not stories:
            self.cancel()
            return self._payload(
                "story_request",
                "Pedile a mamá o papá que te suban un cuento desde el celular.",
            )

        chosen: StoryRecord | None = None
        matched = _match_title(text, stories)
        if matched:
            chosen = matched
        elif _wants_accept(text):
            chosen = random.choice(stories)

        if chosen is None:
            self._offer_retries += 1
            if self._offer_retries >= 2:
                self.cancel()
                return self._payload("story_request", "Después lo leemos.")
            names = self._join_titles(stories)
            return self._payload(
                "story_request",
                f"No te escuché cuál. Tengo {names}. ¿Cuál querés, o cualquiera?",
            )

        return self._start_reading(chosen)

    def _start_reading(self, rec: StoryRecord) -> dict[str, Any]:
        text = self._library.load_text(rec.id)
        if not text:
            remaining = self._library.list_stories()
            if remaining:
                self._state = "offering"
                self._pending_id = remaining[0].id if len(remaining) == 1 else None
                self._offer_retries = 0
                names = self._join_titles(remaining)
                return self._payload(
                    "story_request",
                    f"Ese ya no está. Tengo {names}. ¿Cuál querés?",
                )
            self.cancel()
            return self._payload("story_request", "Ese ya no está.")

        chunks = split_for_speech(text)
        self._state = "awaiting_more"
        self._pending_id = None
        self._offer_retries = 0
        payload = self._payload("story_reading", f"Dale, te leo {rec.title}.")
        payload["story_chunks"] = chunks
        payload["story_closing"] = "¿Querés otro o paramos?"
        payload["skip_tts_truncate"] = True
        return payload

    @staticmethod
    def _join_titles(stories: list[StoryRecord]) -> str:
        titles = [s.title for s in stories]
        if len(titles) == 1:
            return titles[0]
        if len(titles) == 2:
            return f"{titles[0]} y {titles[1]}"
        return ", ".join(titles[:-1]) + f" y {titles[-1]}"

    @staticmethod
    def _payload(intent_name: str, response: str) -> dict[str, Any]:
        return {
            "intent_name": intent_name,
            "confidence": 1.0,
            "response": response,
            "pilar": "cognitivo",
            "skip_tts_truncate": True,
        }
