"""Piper es_AR-daniela-high → WAV. Mismos parámetros de diálogo que la Pi."""
from __future__ import annotations

import urllib.request
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from tts_wav import float_to_wav_bytes

CACHE_DIR = Path.home() / ".edge_ai_models" / "piper"


class PiperEngine:
    MODEL_NAME = "es_AR-daniela-high"
    MODEL_HF_PATH = "es/es_AR/daniela/high"
    LENGTH_SCALE = 1.20
    NOISE_SCALE = 0.667
    NOISE_W_SCALE = 0.98

    def __init__(
        self,
        voice: Any = None,
        voice_loader: Callable[[str], Any] | None = None,
        ensure_model: Callable[[], Path] | None = None,
        cache_dir: Path | None = None,
        retrieve: Callable[[str, Path], Any] | None = None,
    ) -> None:
        self._voice = voice
        self._voice_loader = voice_loader
        self._ensure_model_fn = ensure_model
        self._cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
        self._retrieve = retrieve
        self.ready = False

    def load(self) -> None:
        try:
            if self._voice is None:
                path = (self._ensure_model_fn or self._ensure_model)()
                loader = self._voice_loader or _load_piper_voice
                self._voice = loader(str(path))
            self.ready = self._voice is not None
            if self.ready:
                print("[TTS] Piper listo", flush=True)
        except Exception as exc:
            print(f"[TTS] Piper load falló: {exc}", flush=True)
            self._voice = None
            self.ready = False

    def synthesize(self, text: str) -> bytes:
        if self._voice is None or not (text or "").strip():
            return b""
        chunks: list[np.ndarray] = []
        sample_rate = 22050
        syn_config = _make_syn_config(
            self.LENGTH_SCALE, self.NOISE_SCALE, self.NOISE_W_SCALE
        )
        try:
            for chunk in self._voice.synthesize(text, syn_config=syn_config):
                chunks.append(np.asarray(chunk.audio_float_array, dtype=np.float32))
                sample_rate = int(chunk.sample_rate)
        except Exception as exc:
            print(f"[TTS] Piper synthesize falló: {exc}", flush=True)
            return b""
        if not chunks:
            return b""
        audio = np.concatenate(chunks).astype(np.float32)
        return float_to_wav_bytes(audio, sample_rate)

    def _ensure_model(self) -> Path:
        cache_dir = self._cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_file = cache_dir / f"{self.MODEL_NAME}.onnx"
        config_file = cache_dir / f"{self.MODEL_NAME}.onnx.json"
        if model_file.exists() and config_file.exists():
            return model_file
        base_url = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{self.MODEL_HF_PATH}/{self.MODEL_NAME}"
        )
        retrieve = self._retrieve or urllib.request.urlretrieve
        for suffix, target in ((".onnx", model_file), (".onnx.json", config_file)):
            if not target.exists():
                retrieve(f"{base_url}{suffix}", str(target))
        return model_file


def _load_piper_voice(model_path: str) -> Any:
    try:
        from piper.voice import PiperVoice
    except ImportError:
        from piper import PiperVoice  # type: ignore[attr-defined]
    return PiperVoice.load(model_path)


def _make_syn_config(length_scale: float, noise_scale: float, noise_w_scale: float) -> Any:
    try:
        from piper.config import SynthesisConfig

        return SynthesisConfig(
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w_scale=noise_w_scale,
        )
    except Exception:
        return SimpleNamespace(
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w_scale=noise_w_scale,
        )
