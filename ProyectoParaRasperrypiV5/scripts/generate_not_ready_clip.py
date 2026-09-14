"""Genera el clip pregrabado con Microsoft Edge TTS (una vez, en Windows)."""
from __future__ import annotations

import asyncio
import sys
import wave
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from sleep_state import NOT_READY_TEXT, not_ready_clip_path  # noqa: E402

VOICE = "es-AR-ElenaNeural"


async def _synthesize_mp3(mp3_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(NOT_READY_TEXT, VOICE)
    await communicate.save(str(mp3_path))


def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    import numpy as np

    audio = None
    sample_rate = 24000
    try:
        import soundfile as sf

        data, sample_rate = sf.read(str(mp3_path), dtype="float32")
        audio = data
    except Exception:
        import av

        container = av.open(str(mp3_path))
        stream = container.streams.audio[0]
        sample_rate = int(stream.rate or 24000)
        frames = []
        for frame in container.decode(stream):
            arr = frame.to_ndarray()
            if arr.ndim > 1:
                arr = arr.mean(axis=0)
            frames.append(arr)
        if not frames:
            raise RuntimeError("edge-tts no produjo audio")
        audio = np.concatenate(frames).astype(np.float32)
    if audio is None:
        raise RuntimeError("no pude decodificar el mp3 de Edge TTS")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm_i16 = (pcm * 32767.0).astype("<i2")
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm_i16.tobytes())


def main() -> None:
    wav_path = not_ready_clip_path(APP_DIR)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path = wav_path.with_suffix(".mp3")
    asyncio.run(_synthesize_mp3(mp3_path))
    _mp3_to_wav(mp3_path, wav_path)
    mp3_path.unlink(missing_ok=True)
    print(f"ok {wav_path} ({wav_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
