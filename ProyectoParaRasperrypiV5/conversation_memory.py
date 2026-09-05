"""Historial corto de conversación compartido por Groq y el LLM local."""
from __future__ import annotations

import os
from typing import Any


def default_max_turns() -> int:
    """Default 4. Rollback: CONVO_MAX_TURNS=10."""
    try:
        return max(1, int(os.environ.get("CONVO_MAX_TURNS") or "4"))
    except ValueError:
        return 4


class ConversationMemory:
    """Últimos N turnos (par nene + TEO) para el prompt del LLM."""

    MAX_TURNS = 4

    def __init__(self, max_turns: int | None = None) -> None:
        self.max_turns = default_max_turns() if max_turns is None else max_turns
        self._messages: list[dict[str, str]] = []

    def messages(self) -> list[dict[str, str]]:
        return list(self._messages)

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        user = (user_text or "").strip()
        assistant = (assistant_text or "").strip()
        if not user and not assistant:
            return
        if user:
            self._messages.append({"role": "user", "content": user})
        if assistant:
            self._messages.append({"role": "assistant", "content": assistant})
        self._trim()

    def clear(self) -> None:
        self._messages.clear()

    def _trim(self) -> None:
        max_msgs = self.max_turns * 2
        if len(self._messages) > max_msgs:
            self._messages = self._messages[-max_msgs:]

    def as_debug(self) -> dict[str, Any]:
        return {"turns": len(self._messages) // 2, "messages": self.messages()}
