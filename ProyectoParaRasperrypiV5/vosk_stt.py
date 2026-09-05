"""STT local sin CTranslate2: Vosk (Kaldi).

En esta Raspberry Pi 5, faster-whisper muere con SIGBUS al cargar
(medium/small/tiny, 16K o 4K). Vosk usa otra librería nativa y transcribe
el PCM del micrófono USB local.
"""
from __future__ import annotations

import json
import os
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

APP_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = APP_DIR / "models" / "vosk-model-small-es-0.42"
MODEL_ZIP_URL = "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"

LogFn = Callable[[str], None]


def float32_to_pcm_s16le(audio: np.ndarray) -> bytes:
    mono = np.asarray(audio, dtype=np.float32).reshape(-1)
    clipped = np.clip(mono, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def text_from_vosk_json(raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("text") or "").strip()


VOSK_PCM_CHUNK = 4000


class VoskTranscriber:
    def __init__(self, model: Any) -> None:
        self._model = model
        self._recognizer_factory: Any = None

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[Any], None]:
        del kwargs
        pcm = float32_to_pcm_s16le(np.asarray(audio, dtype=np.float32))
        rec = self._make_recognizer()
        parts: list[str] = []
        for offset in range(0, len(pcm), VOSK_PCM_CHUNK):
            chunk = pcm[offset : offset + VOSK_PCM_CHUNK]
            if rec.AcceptWaveform(chunk):
                piece = text_from_vosk_json(rec.Result())
                if piece:
                    parts.append(piece)
        tail = text_from_vosk_json(rec.FinalResult())
        if tail:
            parts.append(tail)
        text = " ".join(parts).strip()
        if not text:
            return [], None
        return [SimpleNamespace(text=text, avg_logprob=None, no_speech_prob=None)], None

    def _make_recognizer(self) -> Any:
        if self._recognizer_factory is not None:
            return self._recognizer_factory(self._model, 16000)
        from vosk import KaldiRecognizer

        return KaldiRecognizer(self._model, 16000)


def _looks_like_model_dir(path: Path) -> bool:
    return path.is_dir() and (path / "am" / "final.mdl").exists()


def resolve_model_dir() -> Path | None:
    override = (os.environ.get("VOSK_MODEL") or "").strip()
    if override:
        path = Path(override)
        return path if _looks_like_model_dir(path) else None
    if _looks_like_model_dir(DEFAULT_MODEL_DIR):
        return DEFAULT_MODEL_DIR
    return None


def download_model(log: LogFn | None = None) -> Path | None:
    dest = DEFAULT_MODEL_DIR
    if _looks_like_model_dir(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    zip_path = dest.parent / "vosk-model-small-es-0.42.zip"
    if log:
        log("Descargando modelo Vosk español (una vez, ~40 MB)...")
    try:
        urllib.request.urlretrieve(MODEL_ZIP_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest.parent)
    except OSError as exc:
        if log:
            log(f"No pude bajar Vosk: {exc}")
        return None
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
    if _looks_like_model_dir(dest):
        return dest
    if log:
        log("El zip de Vosk no dejó el directorio esperado.")
    return None


def start_vosk(log: LogFn | None = None) -> VoskTranscriber | None:
    try:
        from vosk import Model, SetLogLevel
    except ImportError:
        if log:
            log("Vosk no está instalado. En la Pi: pip install vosk")
        return None
    SetLogLevel(-1)
    model_dir = resolve_model_dir()
    if model_dir is None:
        model_dir = download_model(log=log)
    if model_dir is None:
        if log:
            log(
                "Falta el modelo Vosk. "
                f"wget {MODEL_ZIP_URL} && unzip en {DEFAULT_MODEL_DIR.parent}"
            )
        return None
    try:
        model = Model(str(model_dir))
    except Exception as exc:
        if log:
            log(f"Vosk no cargó el modelo: {exc}")
        return None
    if log:
        log(f"STT Vosk listo ({model_dir.name})")
    return VoskTranscriber(model)
