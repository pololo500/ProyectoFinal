"""Piper + Elena → WAV 16-bit. ready = Piper cargó."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from config import prefer_elena
from tts_elena import synthesize_wav as elena_synthesize_wav
from tts_piper import PiperEngine


class TtsEngine:
    def __init__(
        self,
        piper: Any = None,
        elena_fn: Callable[[str], bytes] | None = None,
        prefer_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._piper = piper if piper is not None else PiperEngine()
        self._elena_fn = elena_fn if elena_fn is not None else elena_synthesize_wav
        self._prefer_fn = prefer_fn if prefer_fn is not None else prefer_elena
        self.ready = False

    def load(self) -> None:
        self._piper.load()
        self.ready = bool(getattr(self._piper, "ready", False))

    def synthesize(self, text: str) -> bytes:
        if not (text or "").strip():
            return b""
        started = time.monotonic()
        motor = "piper"
        wav = b""
        if self._prefer_fn():
            try:
                wav = self._elena_fn(text) or b""
            except Exception as exc:
                print(f"[TTS] Elena falló: {exc}", flush=True)
                wav = b""
            if wav:
                motor = "elena"
        if not wav:
            if not getattr(self._piper, "ready", False):
                return b""
            motor = "piper"
            try:
                wav = self._piper.synthesize(text) or b""
            except Exception as exc:
                print(f"[TTS] Piper synthesize falló: {exc}", flush=True)
                return b""
        ms = (time.monotonic() - started) * 1000.0
        print(f"[TTS] motor={motor} ms={ms:.0f}", flush=True)
        return wav
