"""Mensajes de alerta para la app parental.

Agrupa palabras nuevas para no saturar el celular y describe logros
con lo que realmente hizo el nene.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable


class VocabularyParentAlerter:
    """Acumula palabras nuevas y avisa al padre en bloque.

    No notifica cada token. Dispara un mensaje cuando:
    - se juntan BURST_MIN o más palabras, o
    - hace DROUGHT_HOURS que no había descubrimientos (incluso 1 palabra),
      después de esperar DEBOUNCE_SECONDS para agrupar un chorro.
    """

    BURST_MIN = 5
    DEBOUNCE_SECONDS = 90.0
    DROUGHT_HOURS = 12.0
    MAX_WORDS_IN_MESSAGE = 12

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        self._now = now_fn or datetime.now
        self._pending: list[str] = []
        self._last_add: datetime | None = None
        self._noteworthy = False

    def consider(self, new_words: list[str], hours_since_prior: float | None) -> str | None:
        """Incorpora palabras nuevas y, si corresponde, devuelve el texto del aviso."""
        now = self._now()
        if new_words:
            if hours_since_prior is None or hours_since_prior >= self.DROUGHT_HOURS:
                self._noteworthy = True
            for word in new_words:
                if word not in self._pending:
                    self._pending.append(word)
            self._last_add = now
            if len(self._pending) >= self.BURST_MIN:
                return self._flush()
        return self.poll()

    def poll(self) -> str | None:
        """Llama en cada turno: flushea tras el debounce si el lote vale la pena."""
        now = self._now()
        if not self._pending or self._last_add is None:
            return None
        quiet = (now - self._last_add).total_seconds() >= self.DEBOUNCE_SECONDS
        if not quiet:
            return None
        if self._noteworthy or len(self._pending) >= self.BURST_MIN:
            return self._flush()
        return None

    def flush_session(self) -> str | None:
        """Al apagar el worker: avisa lo pendiente si era sequía o un lote grande."""
        if not self._pending:
            return None
        if self._noteworthy or len(self._pending) >= self.BURST_MIN:
            return self._flush()
        return None

    def _flush(self) -> str:
        words = list(self._pending)
        n = len(words)
        shown = words[: self.MAX_WORDS_IN_MESSAGE]
        listed = ", ".join(shown)
        extra = n - len(shown)
        if extra > 0:
            listed += f" y {extra} más"
        if self._noteworthy and n < self.BURST_MIN:
            msg = (
                "Hacía un tiempo que no aparecía vocabulario nuevo. "
                f"El nene usó por primera vez: {listed}."
            )
        else:
            msg = f"El nene usó {n} palabras nuevas: {listed}."
        self._pending = []
        self._noteworthy = False
        self._last_add = None
        return msg


def describe_child_achievement(
    param: str,
    user_text: str,
    intent_name: str = "",
) -> str:
    """Arma el texto de la notificación de logro para el padre."""
    detail = (param or "").strip()
    if detail:
        return f"El nene logró: {detail}."
    spoken = " ".join((user_text or "").split())
    if spoken:
        if len(spoken) > 90:
            spoken = spoken[:87] + "…"
        return f"El nene logró algo: dijo «{spoken}»."
    intent = (intent_name or "").strip()
    if intent and intent not in {"unknown", ""}:
        return f"El nene logró un avance en la actividad ({intent})."
    return "El nene logró un momento especial jugando con TEO."
