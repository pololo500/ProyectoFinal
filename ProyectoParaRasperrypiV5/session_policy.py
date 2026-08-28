"""Políticas de sesión del peluche: volumen, noche, playtime, privacidad y keywords.

Lógica pura, sin GPIO ni audio, para poder testearla en Windows y en la Pi.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np


def gain_from_limit(volume_limit: int) -> float:
    """Convierte 0–100 parental a ganancia lineal 0.0–1.0."""
    return max(0.0, min(1.0, float(volume_limit) / 100.0))


def apply_gain(audio: np.ndarray, gain: float) -> np.ndarray:
    scaled = audio.astype(np.float32, copy=False) * float(gain)
    return np.clip(scaled, -1.0, 1.0).astype(np.float32)


def effective_volume_limit(volume_limit: int, night_mode: bool) -> int:
    """En modo noche el tope no supera 40 % (estímulo más bajo)."""
    clamped = max(0, min(100, int(volume_limit)))
    if night_mode:
        return min(clamped, 40)
    return clamped


_NIGHT_ALLOWED = {
    "call_parent",
    "crisis_cry",
    "emotion_sad",
    "emotion_fear",
    "tired_sleepy",
    "hug_request",
    "help_request",
    "farewell",
    "sensory_discomfort",
    "needs_basic",
    "greeting",
    "frustration_support",
    "identity_name",
    "body_hurt",
}

NIGHT_DECLINE_PHRASE = (
    "Estoy descansando. Si me necesitás, llamá a mamá o papá."
)

PLAYTIME_DECLINE_PHRASE = "Hoy ya jugamos bastante. Descansemos un rato."


def night_should_engage(intent_name: str, night_mode: bool = True) -> bool:
    if not night_mode:
        return True
    return (intent_name or "") in _NIGHT_ALLOWED


_PLAYTIME_ALLOWED = {
    "call_parent",
    "crisis_cry",
    "help_request",
    "farewell",
    "tired_sleepy",
    "hug_request",
    "emotion_sad",
    "emotion_fear",
    "sensory_discomfort",
    "body_hurt",
}


@dataclass
class PlaytimeGuard:
    """Tope diario de interacción. limit_minutes=0 significa sin límite."""

    limit_minutes: int = 0
    today: date = field(default_factory=date.today)
    _seconds: float = 0.0

    def add_seconds(self, duration_s: float) -> None:
        if date.today() != self.today:
            self.today = date.today()
            self._seconds = 0.0
        self._seconds += max(0.0, float(duration_s))

    def is_over_limit(self) -> bool:
        if self.limit_minutes <= 0:
            return False
        return self._seconds >= self.limit_minutes * 60.0

    def allows_intent(self, intent_name: str) -> bool:
        if not self.is_over_limit():
            return True
        return (intent_name or "") in _PLAYTIME_ALLOWED


_NOTIF_BLOCKED_KEYS = {"text", "utterance", "response_given", "transcript"}


def sanitize_notification_extra(extra: dict[str, Any] | None) -> dict[str, Any] | None:
    """Nunca envía el texto crudo del nene a la app parental."""
    if extra is None:
        return None
    cleaned = {k: v for k, v in extra.items() if k not in _NOTIF_BLOCKED_KEYS}
    return cleaned or None


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower().strip()


_BARGE_IN = re.compile(
    r"\b(basta|parar|paro|para|chau|silencio|mama|papa|mamá|papá)\b",
    re.IGNORECASE,
)


def is_barge_in_text(text: str) -> bool:
    return bool(_BARGE_IN.search(_normalize(text)))


ECHO_MUTE_SECONDS = 0.40


def mic_open_for_listen(speaker_playing: bool, now: float, echo_mute_until: float) -> bool:
    """Half-duplex: el mic no escucha mientras el parlante suena ni en la cola de eco."""
    if speaker_playing:
        return False
    return now >= echo_mute_until


def is_clear_keyword_intent(text: str) -> str | None:
    """Intents que no deben esperar embeddings ni un Whisper “perfecto”."""
    normalized = _normalize(text)
    if re.search(
        r"piedra.{0,40}papel|papel.{0,30}tijera|piedra\s*papel|juguem\w*.{0,25}tijera",
        normalized,
    ):
        return "play_piedra_papel"
    if re.search(r"\bveo[\s\-]?veo\b", normalized):
        return "play_veo_veo"
    if re.search(
        r"(cont(a|ame)|lee(me)?|narra(me)?).{0,24}cuento|\b(un|el)\s+cuento\b|\bcuentos\b",
        normalized,
    ):
        return "story_request"
    if re.search(
        r"\b(tengo hambre|tengo sed|quiero agua|quiero comer)\b",
        normalized,
    ):
        return "needs_basic"
    if re.search(
        r"\b(par[aoá]|paro|cort[aá]|stop|silencio|apag[aá]r?).{0,25}(m[uú]sica|canci)",
        normalized,
    ):
        return "stop_music_request"
    if re.search(r"\b(abraz|abrazo|abrazame|dame un abrazo)\b", normalized):
        return "hug_request"
    if re.search(r"\b(yoga|estirarme|hagamos yoga|quiero moverme)\b", normalized):
        return "yoga_request"
    if re.search(r"como te llam|quien sos|cual es tu nombre", normalized):
        return "identity_name"
    if re.search(
        r"(llama|llame|llamar|avisale|avisa).{0,24}(mama|papa|mamá|papá)"
        r"|quiero hablar con (mama|papa|mamá|papá)"
        r"|hablar con (mama|papa|mamá|papá)",
        normalized,
    ):
        return "call_parent"
    if re.search(
        r"\b(canci[oó]n|m[uú]sica|cantame|canta\b|reproduc[ií].{0,12}canci|"
        r"pon[ée]\s+(una\s+)?(canci|m[uú]sica)|escuchar\s+m[uú]sica)\b",
        normalized,
    ):
        return "song_request"
    return None


MUTE_FAILSAFE_TURNS = 3
_GAME_KEYWORDS_WHILE_MUTED = frozenset({"play_veo_veo", "play_piedra_papel"})
_CHILD_TEXT_LOG_MAX = 80
LogFn = Callable[..., None]


def should_run_intent_dispatcher(muted: bool) -> bool:
    return not muted


def game_keyword_while_muted(muted: bool, keyword: str | None) -> str | None:
    if not muted or not keyword:
        return None
    if keyword in _GAME_KEYWORDS_WHILE_MUTED:
        return keyword
    return None


def _clip_child_text(text: str) -> str:
    clipped = (text or "").strip()
    if len(clipped) > _CHILD_TEXT_LOG_MAX:
        return clipped[:_CHILD_TEXT_LOG_MAX]
    return clipped


class IntentMute:
    """Apaga el despacho de intents mientras el LLM espera una respuesta."""

    def __init__(self, log_fn: LogFn | None = None) -> None:
        self._muted = False
        self.turns_while_muted = 0
        self._log_fn = log_fn

    @property
    def is_muted(self) -> bool:
        return self._muted

    def apply_tag(self, on: bool, reason: str, child_text: str = "") -> bool:
        want_muted = not on
        if want_muted == self._muted:
            return False
        old = "off" if self._muted else "on"
        self._muted = want_muted
        if not self._muted:
            self.turns_while_muted = 0
        else:
            self.turns_while_muted = 0
        new = "off" if self._muted else "on"
        self._emit(old, new, reason, child_text)
        return True

    def note_game_keyword(self, child_text: str) -> None:
        self.apply_tag(on=True, reason="game_keyword", child_text=child_text)

    def note_child_turn_still_muted(self, child_text: str = "") -> None:
        if not self._muted:
            return
        self.turns_while_muted += 1
        if self.turns_while_muted >= MUTE_FAILSAFE_TURNS:
            self.apply_tag(on=True, reason="failsafe", child_text=child_text)

    def reset(self) -> None:
        self.apply_tag(on=True, reason="llm_tag", child_text="")

    def _emit(self, old: str, new: str, reason: str, child_text: str) -> None:
        message = f"{old}→{new} reason={reason}"
        clipped = _clip_child_text(child_text)
        if clipped:
            message += f' text="{clipped}"'
        if self._log_fn is not None:
            self._log_fn("INTENTS", message)
            return
        from debug_logger import get_debug_logger, log_action

        log_action("INTENTS", message)
        logger = get_debug_logger()
        if logger is not None:
            logger.log_output("INTENTS", message)


def apply_llm_intent_actions(
    mute: IntentMute,
    actions: list[dict[str, str]],
    child_text: str = "",
) -> None:
    """Aplica INTENTS_ON/OFF (último gana). NOTIFY_PARENT fuerza ON."""
    last_on: bool | None = None
    notify = False
    for item in actions:
        name = str(item.get("action") or "").upper()
        if name == "INTENTS_ON":
            last_on = True
        elif name == "INTENTS_OFF":
            last_on = False
        elif name == "NOTIFY_PARENT":
            notify = True
    if last_on is not None:
        mute.apply_tag(on=last_on, reason="llm_tag", child_text=child_text)
    if notify:
        mute.apply_tag(on=True, reason="notify_parent", child_text=child_text)


def telemetry_range_summary(data_dir: Path, start: date, end: date) -> dict[str, Any]:
    """Agrega telemetry_YYYY-MM-DD.json entre start y end inclusive."""
    totals = {
        "total_interactions": 0,
        "total_duration_s": 0.0,
        "pillar_counts": {},
        "crisis_count": 0,
        "games_played": 0,
        "routines_completed": 0,
        "new_words_today": 0,
        "days": 0,
        "daily": [],
    }
    day = start
    while day <= end:
        path = data_dir / f"telemetry_{day.isoformat()}.json"
        totals["days"] += 1
        day_row = {
            "date": day.isoformat(),
            "interactions": 0,
            "duration_s": 0.0,
            "crisis_count": 0,
            "games_played": 0,
            "routines_completed": 0,
            "new_words": 0,
        }
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summary = data.get("summary") or {}
                interactions = int(summary.get("total_interactions") or 0)
                duration_s = float(summary.get("total_duration_s") or 0.0)
                crisis = int(summary.get("crisis_count") or 0)
                games = int(summary.get("games_played") or 0)
                routines = int(summary.get("routines_completed") or 0)
                new_words = int(summary.get("new_words_today") or 0)
                totals["total_interactions"] += interactions
                totals["total_duration_s"] += duration_s
                totals["crisis_count"] += crisis
                totals["games_played"] += games
                totals["routines_completed"] += routines
                totals["new_words_today"] += new_words
                day_row.update(
                    {
                        "interactions": interactions,
                        "duration_s": duration_s,
                        "crisis_count": crisis,
                        "games_played": games,
                        "routines_completed": routines,
                        "new_words": new_words,
                    }
                )
                for pilar, count in (summary.get("pillar_counts") or {}).items():
                    bucket = totals["pillar_counts"]
                    bucket[pilar] = int(bucket.get(pilar, 0)) + int(count)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        totals["daily"].append(day_row)
        day += timedelta(days=1)
    return totals
