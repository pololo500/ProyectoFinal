"""Elena Neural (edge-tts) → WAV. Misma voz que ProyectoTtsMp3."""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from tts_wav import float_to_wav_bytes

VOICE_NAME = "es-AR-ElenaNeural"
VOICE_RATE = "-8%"
ELENA_TIMEOUT_S = 6.0


def prepare_tts_text(text: str) -> str:
    cleaned = re.sub(r"\s{2,}", " ", text).strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?…":
        cleaned += "."
    return cleaned


def synthesize_wav(
    text: str,
    timeout_s: float = ELENA_TIMEOUT_S,
    communicate_factory: Callable[..., Any] | None = None,
    decode_mp3: Callable[[bytes], tuple[np.ndarray | None, int]] | None = None,
) -> bytes:
    speech = prepare_tts_text(text or "")
    if not speech:
        return b""

    def _run() -> bytes:
        mp3 = asyncio.run(_synthesize_mp3(speech, communicate_factory))
        if not mp3:
            return b""
        decoder = decode_mp3 or _decode_mp3
        audio, sr = decoder(mp3)
        if audio is None or getattr(audio, "size", 0) == 0:
            return b""
        return float_to_wav_bytes(np.asarray(audio, dtype=np.float32), int(sr))

    return _run_with_timeout(_run, timeout_s)


def _run_with_timeout(fn: Callable[[], bytes], timeout_s: float) -> bytes:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except (concurrent.futures.TimeoutError, Exception):
        return b""
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


async def _synthesize_mp3(
    speech: str,
    communicate_factory: Callable[..., Any] | None,
) -> bytes:
    factory = communicate_factory
    if factory is None:
        import edge_tts

        factory = edge_tts.Communicate
    fd, name = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    dest = Path(name)
    try:
        communicate = factory(speech, VOICE_NAME, rate=VOICE_RATE)
        await communicate.save(str(dest))
        return dest.read_bytes()
    finally:
        dest.unlink(missing_ok=True)


def _decode_mp3(mp3_data: bytes) -> tuple[np.ndarray | None, int]:
    try:
        import soundfile as sf

        audio_array, sample_rate = sf.read(io.BytesIO(mp3_data), dtype="float32")
        if getattr(audio_array, "ndim", 1) > 1:
            audio_array = audio_array[:, 0]
        return np.asarray(audio_array, dtype=np.float32), int(sample_rate)
    except Exception:
        pass
    try:
        import minimp3

        decoder = minimp3.Decoder()
        frames = decoder.decode(mp3_data)
        audio_int16 = np.frombuffer(frames[0], dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0, int(frames[1])
    except Exception:
        pass
    try:
        from pydub import AudioSegment

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_data)
            tmp_path = tmp.name
        try:
            audio_seg = AudioSegment.from_mp3(tmp_path)
            audio_seg = audio_seg.set_channels(1)
            samples = np.array(audio_seg.get_array_of_samples(), dtype=np.float32)
            samples /= 32768.0
            return samples, int(audio_seg.frame_rate)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        return None, 0
