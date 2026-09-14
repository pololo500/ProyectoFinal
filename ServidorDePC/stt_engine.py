"""Whisper GPU (faster-whisper large-v3 float16)."""
from __future__ import annotations

import io
import wave
from typing import Any

import numpy as np

from config import WHISPER_COMPUTE, WHISPER_DEVICE, WHISPER_INITIAL_PROMPT, WHISPER_MODEL


class SttEngine:
    def __init__(self) -> None:
        self._model: Any = None
        self.ready = False

    def load(self) -> None:
        from faster_whisper import WhisperModel

        print(
            f"[STT] Cargando {WHISPER_MODEL} device={WHISPER_DEVICE} compute={WHISPER_COMPUTE}",
            flush=True,
        )
        self._model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        self.ready = True
        print("[STT] listo", flush=True)

    def transcribe_wav(self, wav: bytes, language: str = "es") -> str:
        if self._model is None:
            return ""
        audio = _wav_to_float32(wav)
        if audio.size == 0:
            return ""
        segments, _info = self._model.transcribe(
            audio,
            language=language or "es",
            vad_filter=False,
            beam_size=1,
            initial_prompt=WHISPER_INITIAL_PROMPT,
        )
        parts = [str(getattr(seg, "text", "") or "").strip() for seg in segments]
        return " ".join(p for p in parts if p).strip()


def _wav_to_float32(wav: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(wav), "rb") as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
    except Exception:
        return np.zeros(0, dtype=np.float32)
    if sw != 2 or not raw:
        return np.zeros(0, dtype=np.float32)
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if nch > 1:
        pcm = pcm.reshape(-1, nch).mean(axis=1)
    if sr != 16000 and sr > 0:
        # Downsample entero simple (48k→16k = cada 3).
        step = max(1, int(round(sr / 16000.0)))
        pcm = pcm[::step]
    return pcm.astype(np.float32)
