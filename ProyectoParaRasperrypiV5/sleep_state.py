"""Máquina de estados prendido/apagado (sueño) de Teo.

Lógica pura, sin GPIO ni audio, para testearla en Windows y en la Pi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from session_policy import _normalize, _phrase_key, is_clear_keyword_intent

Phase = Literal["loading", "asleep", "awake"]
BellyAction = Literal["hug", "wake", "queue", "ignore"]
WakeResult = Literal["woke", "queued", "blocked", "already_on"]
SleepReason = Literal["app", "playtime", "child"]
WakeSource = Literal["app", "belly"]

SLEEP_CONFIRM_PHRASE = "¿Querés que me vaya a dormir?"
SLEEP_GOODNIGHT_PHRASE = "Bueno, me voy a dormir."
NOT_READY_TEXT = "Todavía no estoy listo, dame unos segundos más."
NOT_READY_CLIP_NAME = "todavia_no_estoy_listo.wav"

_YES_PHRASES = frozenset(
    {
        "si",
        "sip",
        "dale",
        "bueno",
        "ok",
        "okay",
        "si quiero",
        "si teo",
        "dale teo",
        "bueno teo",
    }
)

_NO_PLAY_RE = re.compile(r"\bno quiero(?: jugar)?(?: mas| más)?\b")
_SLEEP_OFF_RE = re.compile(
    r"\b(?:chau|chao|adios)\b"
    r"|\bnos vemos\b"
    r"|\bhasta luego\b"
    r"|\b(?:me )?voy a dormir\b"
    r"|\bapagate(?: teo)?\b"
    r"|\bteo apaga(?:te)?\b"
    r"|\bapaga teo\b"
    r"|\b(?:vete|andate|vamos) a dormir\b"
)


def not_ready_clip_path(app_dir: Path) -> Path:
    preferred = Path(app_dir) / "assets" / NOT_READY_CLIP_NAME
    if preferred.exists():
        return preferred
    fallback = Path(app_dir) / NOT_READY_CLIP_NAME
    if fallback.exists():
        return fallback
    return preferred


def is_sleep_confirm_yes(text: str) -> bool:
    key = _phrase_key(_normalize(text))
    if key in _YES_PHRASES:
        return True
    parts = key.split(" ", 1)
    if not parts or parts[0] not in _YES_PHRASES or len(parts) == 1:
        return False
    return is_sleep_request_text(parts[1])


def is_sleep_request_text(text: str) -> bool:
    if is_clear_keyword_intent(text) == "farewell":
        return True
    key = _phrase_key(_normalize(text))
    if _NO_PLAY_RE.search(key):
        return True
    return bool(_SLEEP_OFF_RE.search(key))


def child_sleep_decision(text: str, *, awaiting: bool) -> Literal["sleep", "ask", "continue"]:
    yes = is_sleep_confirm_yes(text)
    request = is_sleep_request_text(text)
    if awaiting:
        if yes or request:
            return "sleep"
        return "continue"
    if request and yes:
        return "sleep"
    if request:
        return "ask"
    return "continue"


@dataclass
class SleepState:
    power_on: bool = False
    models_ready: bool = False
    pending_wake: bool = False
    belly_wake_enabled: bool = True
    playtime_belly_blocked_on: date | None = None
    awaiting_sleep_confirm: bool = False
    _today: date = field(default_factory=date.today)

    def phase(self) -> Phase:
        if self.power_on:
            return "awake"
        if self.models_ready:
            return "asleep"
        return "loading"

    def status_power_on(self) -> bool:
        return self.power_on or self.pending_wake

    def set_belly_wake_enabled(self, enabled: bool) -> None:
        self.belly_wake_enabled = bool(enabled)

    def note_parent_wake(self) -> None:
        self.playtime_belly_blocked_on = None

    def _sync_today(self, today: date | None) -> date:
        current = today or date.today()
        if current != self._today:
            self._today = current
            self.playtime_belly_blocked_on = None
        return current

    def belly_blocked(self, today: date | None = None) -> bool:
        current = self._sync_today(today)
        return self.playtime_belly_blocked_on == current

    def on_belly(self, today: date | None = None) -> BellyAction:
        current = self._sync_today(today)
        if self.phase() == "awake":
            return "hug"
        if not self.belly_wake_enabled or self.belly_blocked(today=current):
            return "ignore"
        if self.phase() == "loading":
            self.pending_wake = True
            return "queue"
        self._wake()
        return "wake"

    def request_wake(self, source: WakeSource, today: date | None = None) -> WakeResult:
        current = self._sync_today(today)
        if source == "belly":
            action = self.on_belly(today=current)
            return {
                "hug": "already_on",
                "wake": "woke",
                "queue": "queued",
                "ignore": "blocked",
            }[action]
        if self.phase() == "awake":
            return "already_on"
        if self.phase() == "loading":
            self.pending_wake = True
            return "queued"
        self._wake()
        return "woke"

    def request_sleep(self, reason: SleepReason, today: date | None = None) -> None:
        current = self._sync_today(today)
        self.power_on = False
        self.pending_wake = False
        self.awaiting_sleep_confirm = False
        if reason == "playtime":
            self.playtime_belly_blocked_on = current

    def mark_models_ready(self) -> bool:
        self.models_ready = True
        if self.pending_wake:
            self._wake()
            return True
        return False

    def _wake(self) -> None:
        self.power_on = True
        self.pending_wake = False
        self.awaiting_sleep_confirm = False
