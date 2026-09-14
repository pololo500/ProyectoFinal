"""Configuración del servidor PC (puerto, token, modelos)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKEN_PATH = ROOT / "pc_server_token.txt"
HOST = os.environ.get("PC_SERVER_BIND") or "0.0.0.0"
PORT = int(os.environ.get("PC_SERVER_PORT") or "8090")
WHISPER_MODEL = os.environ.get("PC_WHISPER_MODEL") or "large-v3"
WHISPER_DEVICE = os.environ.get("PC_WHISPER_DEVICE") or "cuda"
WHISPER_COMPUTE = os.environ.get("PC_WHISPER_COMPUTE") or "float16"
LLM_REPO = os.environ.get("PC_LLM_HF_REPO") or "bartowski/google_gemma-3-12b-it-GGUF"
LLM_GGUF = os.environ.get("PC_LLM_GGUF") or "google_gemma-3-12b-it-Q5_K_M.gguf"
LLM_N_CTX = int(os.environ.get("PC_LLM_N_CTX") or "2048")
LLM_N_GPU_LAYERS = int(os.environ.get("PC_LLM_N_GPU_LAYERS") or "-1")
MODELS_DIR = Path(os.environ.get("PC_MODELS_DIR") or (Path.home() / ".edge_ai_models" / "llm"))

WHISPER_INITIAL_PROMPT = (
    "Hola. ¿Cómo estás? Quiero jugar a piedra, papel o tijera. "
    "Sí, dale. No quiero. Juguemos. Contame un cuento."
)

LLM_STOP = [
    "<end_of_turn>",
    "<start_of_turn>",
    "<|eot_id|>",
    "<|im_end|>",
    "<|endoftext|>",
]

TTS_MAX_CHARS = int(os.environ.get("PC_TTS_MAX_CHARS") or "500")
TTS_LANGUAGE = os.environ.get("PC_TTS_LANGUAGE") or "es"
PREFER_ELENA_PATH = Path(
    os.environ.get("PC_TTS_PREFER_ELENA_FILE") or (ROOT / "tts_prefer_elena.txt")
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def prefer_elena(
    env: dict[str, str] | None = None,
    path: Path | None = None,
) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get("PC_TTS_PREFER_ELENA") or "").strip()
    if raw:
        return _parse_flag(raw)
    file_path = path if path is not None else PREFER_ELENA_PATH
    try:
        line = next(
            (ln.strip() for ln in file_path.read_text(encoding="utf-8").splitlines() if ln.strip()),
            "",
        )
    except OSError:
        line = ""
    if line:
        return _parse_flag(line)
    return True


def _parse_flag(raw: str) -> bool:
    key = raw.strip().lower()
    if key in _FALSE:
        return False
    return True


def load_or_create_token() -> str:
    env = (os.environ.get("PC_SERVER_TOKEN") or "").strip()
    if env:
        return env
    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_hex(16)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    return token
