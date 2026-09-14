"""Rutas HTTP puras: se testean sin FastAPI ni GPU."""
from __future__ import annotations

import io
import json
import time
import wave
from typing import Any, Callable

LogFn = Callable[[str], None]


def _emit(log_fn: LogFn | None, msg: str) -> None:
    if log_fn is None:
        return
    log_fn(msg)


def _clip(text: str, limit: int = 120) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) > limit:
        return t[: limit - 1] + "…"
    return t


def _wav_meta(wav: bytes) -> str:
    n = len(wav or b"")
    extra = ""
    try:
        with wave.open(io.BytesIO(wav or b""), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
        if rate > 0:
            extra = f", {frames / float(rate):.2f}s audio"
    except Exception:
        extra = ""
    return f"{n} bytes{extra}"


def _authorized(expected: str, header: str | None) -> bool:
    got = (header or "").strip()
    if not expected:
        return False
    prefix = "Bearer "
    if got.startswith(prefix):
        got = got[len(prefix):].strip()
    return got == expected


def handle_health(
    stt: Any,
    llm: Any,
    token: str,
    auth_header: str | None,
    tts: Any = None,
) -> tuple[int, dict[str, Any]]:
    if not _authorized(token, auth_header):
        return 401, {"error": "unauthorized"}
    stt_ok = bool(getattr(stt, "ready", False))
    llm_ok = bool(getattr(llm, "ready", False))
    tts_ok = bool(getattr(tts, "ready", False))
    body = {
        "status": "ok" if (stt_ok and llm_ok) else "loading",
        "stt": stt_ok,
        "llm": llm_ok,
        "tts": tts_ok,
    }
    if stt_ok and llm_ok:
        return 200, body
    return 503, body


def handle_transcribe(
    stt: Any,
    llm: Any,
    token: str,
    auth_header: str | None,
    wav: bytes,
    content_type: str | None,
    language: str,
    log_fn: LogFn | None = None,
    peer: str | None = None,
) -> tuple[int, dict[str, Any]]:
    del llm, content_type
    if not _authorized(token, auth_header):
        return 401, {"error": "unauthorized"}
    if not getattr(stt, "ready", False):
        return 503, {"error": "stt not ready"}
    who = peer or "?"
    _emit(log_fn, f"[STT] audio recibido de {who}: {_wav_meta(wav)}")
    t0 = time.perf_counter()
    text = stt.transcribe_wav(wav, language=language or "es")
    ms = (time.perf_counter() - t0) * 1000.0
    shown = str(text or "")
    _emit(log_fn, f'[STT] transcripción {ms:.0f} ms: "{_clip(shown)}"')
    return 200, {"text": shown}


def handle_chat(
    stt: Any,
    llm: Any,
    token: str,
    auth_header: str | None,
    raw_body: bytes,
    log_fn: LogFn | None = None,
    peer: str | None = None,
) -> tuple[int, dict[str, Any]]:
    del stt
    if not _authorized(token, auth_header):
        return 401, {"error": "unauthorized"}
    if not getattr(llm, "ready", False):
        return 503, {"error": "llm not ready"}
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return 400, {"error": "invalid json"}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return 400, {"error": "messages required"}
    who = peer or "?"
    _emit(log_fn, f"[LLM] prompt recibido de {who}: {len(messages)} mensajes")
    t0 = time.perf_counter()
    content = llm.complete(messages)
    ms = (time.perf_counter() - t0) * 1000.0
    shown = str(content or "")
    _emit(log_fn, f'[LLM] respuesta {ms:.0f} ms: "{_clip(shown)}"')
    return 200, {
        "choices": [{"message": {"role": "assistant", "content": shown}}],
    }


def handle_speech(
    tts: Any,
    token: str,
    auth_header: str | None,
    raw_body: bytes,
    log_fn: LogFn | None = None,
    peer: str | None = None,
) -> tuple[int, bytes | dict[str, Any], str]:
    if not _authorized(token, auth_header):
        return 401, {"error": "unauthorized"}, "application/json"
    if not getattr(tts, "ready", False):
        return 503, {"error": "tts not ready"}, "application/json"
    try:
        from config import TTS_MAX_CHARS
    except Exception:
        TTS_MAX_CHARS = 500
    try:
        payload = json.loads((raw_body or b"").decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {"error": "invalid json"}, "application/json"
    if not isinstance(payload, dict):
        return 400, {"error": "invalid json"}, "application/json"
    text = str(payload.get("input") or "").strip()
    if not text:
        return 400, {"error": "input required"}, "application/json"
    if len(text) > int(TTS_MAX_CHARS):
        return 400, {"error": "input too long"}, "application/json"
    who = peer or "?"
    _emit(log_fn, f'[TTS] texto de {who}: "{_clip(text)}"')
    t0 = time.perf_counter()
    wav = tts.synthesize(text)
    ms = (time.perf_counter() - t0) * 1000.0
    if not isinstance(wav, (bytes, bytearray)) or not wav:
        return 500, {"error": "tts failed"}, "application/json"
    _emit(log_fn, f"[TTS] wav {ms:.0f} ms: {_wav_meta(bytes(wav))}")
    return 200, bytes(wav), "audio/wav"
