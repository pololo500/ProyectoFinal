"""Gemma 3 12B IT Q5 en GPU (llama-cpp-python)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import (
    LLM_GGUF,
    LLM_N_CTX,
    LLM_N_GPU_LAYERS,
    LLM_REPO,
    LLM_STOP,
    MODELS_DIR,
)


class LlmEngine:
    def __init__(self) -> None:
        self._llm: Any = None
        self.ready = False

    def load(self) -> None:
        from llama_cpp import Llama

        model_path = _ensure_model()
        n_gl = LLM_N_GPU_LAYERS
        print(
            f"[LLM] Cargando {model_path.name} n_ctx={LLM_N_CTX} n_gpu_layers={n_gl}",
            flush=True,
        )
        self._llm = Llama(
            model_path=str(model_path),
            n_ctx=LLM_N_CTX,
            n_gpu_layers=n_gl,
            n_batch=256,
            verbose=True,
        )
        self.warmup()
        self.ready = True
        print("[LLM] listo", flush=True)

    def warmup(self) -> None:
        if self._llm is None:
            return
        self._llm.create_chat_completion(
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
            temperature=0.0,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self._llm is None:
            return ""
        result = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=80,
            temperature=0.70,
            top_p=0.9,
            top_k=40,
            repeat_penalty=1.15,
            stop=LLM_STOP,
        )
        return (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )


def _ensure_model() -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / LLM_GGUF
    if model_path.exists() and model_path.stat().st_size > 100_000_000:
        return model_path
    from huggingface_hub import hf_hub_download

    downloaded = hf_hub_download(
        repo_id=LLM_REPO,
        filename=LLM_GGUF,
        local_dir=MODELS_DIR,
    )
    return Path(downloaded)
