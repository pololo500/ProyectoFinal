"""Cliente HTTP IPv4 hacia ServidorDePC (STT + LLM) con circuit breaker."""
from __future__ import annotations

import http.client
import io
import json
import os
import socket
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import numpy as np

RequestFn = Callable[..., tuple[int, bytes]]

DEFAULT_CACHE = Path(__file__).resolve().parent / "pc_server_url.txt"
DEFAULT_TOKEN_PATH = Path(__file__).resolve().parent / "pc_server_token.txt"
HEALTH_TIMEOUT_S = 0.3
HEALTH_ATTEMPTS = 5
HEALTH_RETRY_DELAY_S = 0.2
STT_TIMEOUT_S = 25.0
LLM_TIMEOUT_S = 60.0
TTS_TIMEOUT_S = 10.0
FAIL_THRESHOLD = 2
COOLDOWN_S = 30.0


def pcm_float32_to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    mono = np.asarray(audio, dtype=np.float32).reshape(-1)
    clipped = np.clip(mono, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def open_ipv4_tcp(host: str, port: int, timeout_s: float) -> socket.socket:
    """TCP IPv4. Python 3.11 no acepta family= en socket.create_connection()."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout_s)
        sock.connect((host, port))
        return sock
    except Exception:
        sock.close()
        raise


def _normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _is_wav_body(raw: bytes) -> bool:
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PcServerClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        request_fn: RequestFn | None = None,
        cache_path: Path | None = None,
        token_path: Path | None = None,
        health_timeout_s: float = HEALTH_TIMEOUT_S,
        stt_timeout_s: float = STT_TIMEOUT_S,
        llm_timeout_s: float = LLM_TIMEOUT_S,
        fail_threshold: int = FAIL_THRESHOLD,
        cooldown_s: float = COOLDOWN_S,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.token = (token or "").strip()
        self._request_fn = request_fn
        self.cache_path = cache_path if cache_path is not None else DEFAULT_CACHE
        self.token_path = token_path if token_path is not None else DEFAULT_TOKEN_PATH
        self.health_timeout_s = health_timeout_s
        self.stt_timeout_s = stt_timeout_s
        self.llm_timeout_s = llm_timeout_s
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self.fail_count = 0
        self.open_until = 0.0
        self.fail_count_tts = 0
        self.open_until_tts = 0.0
        self._http_lock = threading.Lock()

    @classmethod
    def from_env(
        cls,
        cache_path: Path | None = None,
        token_path: Path | None = None,
    ) -> "PcServerClient":
        target = cache_path if cache_path is not None else DEFAULT_CACHE
        tok_file = token_path if token_path is not None else (
            target.parent / "pc_server_token.txt" if target is not None else DEFAULT_TOKEN_PATH
        )
        url = _normalize_base_url(os.environ.get("PC_SERVER_URL") or "")
        if not url and target.exists():
            url = _normalize_base_url(target.read_text(encoding="utf-8"))
        token = (os.environ.get("PC_SERVER_TOKEN") or "").strip()
        if not token and tok_file.exists():
            token = tok_file.read_text(encoding="utf-8").strip()
        return cls(url, token, cache_path=target, token_path=tok_file)

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self.open_until

    @property
    def circuit_tts_open(self) -> bool:
        return time.monotonic() < self.open_until_tts

    def can_attempt(self) -> bool:
        return bool(self.base_url) and bool(self.token) and not self.circuit_open

    def can_attempt_tts(self) -> bool:
        return bool(self.base_url) and bool(self.token) and not self.circuit_tts_open

    def health(self) -> bool:
        return self._health_once(record_fail=True)

    def health_ready(
        self,
        attempts: int = HEALTH_ATTEMPTS,
        retry_delay_s: float = HEALTH_RETRY_DELAY_S,
        on_try: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Hasta `attempts` GET /health. El circuit no se abre en los reintentos intermedios."""
        total = max(1, int(attempts))
        delay = max(0.0, float(retry_delay_s))
        for i in range(1, total + 1):
            if on_try is not None:
                on_try(i, total)
            last = i == total
            ok = self._health_once(record_fail=last)
            if ok:
                return True
            if self.circuit_open:
                return False
            if not last and delay:
                time.sleep(delay)
        return False

    def _health_once(self, *, record_fail: bool) -> bool:
        status, raw = self._call(
            "GET",
            "/health",
            timeout_s=self.health_timeout_s,
            record_fail=record_fail,
        )
        del raw
        if status is None:
            return False
        if status == 503:
            return False
        if status == 401:
            self._open_circuit()
            return False
        if status != 200:
            if record_fail:
                self._infra_fail()
            return False
        self._on_success()
        return True

    def transcribe(self, wav: bytes) -> dict[str, Any] | None:
        status, raw = self._call(
            "POST",
            "/v1/audio/transcriptions",
            body=wav,
            content_type="audio/wav",
            timeout_s=self.stt_timeout_s,
        )
        if status is None:
            return None
        if status == 401:
            self._open_circuit()
            return None
        if status != 200:
            self._infra_fail()
            return None
        self._on_success()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return {
            "text": str(payload.get("text") or ""),
            "avg_logprob": _opt_float(payload.get("avg_logprob")),
            "no_speech_prob": _opt_float(payload.get("no_speech_prob")),
        }

    def complete(self, messages: list[dict[str, str]]) -> str | None:
        body = json.dumps({
            "messages": messages,
            "max_tokens": 80,
            "temperature": 0.70,
            "top_p": 0.9,
        }).encode("utf-8")
        status, raw = self._call(
            "POST",
            "/v1/chat/completions",
            body=body,
            content_type="application/json",
            timeout_s=self.llm_timeout_s,
        )
        if status is None:
            return None
        if status == 401:
            self._open_circuit()
            return None
        if status != 200:
            self._infra_fail()
            return None
        self._on_success()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        return str(message.get("content") or "").strip()

    def synthesize(self, text: str) -> bytes | None:
        body = json.dumps({"input": text, "language": "es"}).encode("utf-8")
        status, raw = self._call(
            "POST",
            "/v1/audio/speech",
            body=body,
            content_type="application/json",
            timeout_s=TTS_TIMEOUT_S,
            circuit="tts",
        )
        if status is None:
            return None
        if status == 401:
            self._open_circuit_tts()
            return None
        if status == 503:
            return None
        if status != 200:
            self._infra_fail_tts()
            return None
        if not _is_wav_body(raw):
            self._infra_fail_tts()
            return None
        self._on_success_tts()
        return raw

    def _open_circuit(self) -> None:
        self.fail_count = self.fail_threshold
        self.open_until = time.monotonic() + self.cooldown_s

    def _open_circuit_tts(self) -> None:
        self.fail_count_tts = self.fail_threshold
        self.open_until_tts = time.monotonic() + self.cooldown_s

    def _infra_fail(self) -> None:
        self.fail_count += 1
        if self.fail_count >= self.fail_threshold:
            self.open_until = time.monotonic() + self.cooldown_s

    def _infra_fail_tts(self) -> None:
        self.fail_count_tts += 1
        if self.fail_count_tts >= self.fail_threshold:
            self.open_until_tts = time.monotonic() + self.cooldown_s

    def _on_success(self) -> None:
        self.fail_count = 0
        self.open_until = 0.0
        self._cache_url()

    def _on_success_tts(self) -> None:
        self.fail_count_tts = 0
        self.open_until_tts = 0.0
        self._cache_url()

    def _cache_url(self) -> None:
        if self.base_url and self.cache_path is not None:
            try:
                self.cache_path.write_text(self.base_url + "\n", encoding="utf-8")
            except OSError:
                pass

    def _call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout_s: float = HEALTH_TIMEOUT_S,
        record_fail: bool = True,
        circuit: str = "main",
    ) -> tuple[int | None, bytes]:
        if not self.base_url:
            return None, b""
        if circuit == "tts":
            if self.circuit_tts_open:
                return None, b""
        elif self.circuit_open:
            return None, b""
        try:
            with self._http_lock:
                if self._request_fn is not None:
                    status, raw = self._request_fn(
                        method, path, body=body, content_type=content_type, timeout_s=timeout_s
                    )
                else:
                    status, raw = self._http_request(
                        method, path, body=body, content_type=content_type, timeout_s=timeout_s
                    )
        except (TimeoutError, socket.timeout, ConnectionError, OSError, http.client.HTTPException, TypeError):
            if record_fail:
                if circuit == "tts":
                    self._infra_fail_tts()
                else:
                    self._infra_fail()
            return None, b""
        return int(status), raw

    def _http_request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout_s: float = HEALTH_TIMEOUT_S,
    ) -> tuple[int, bytes]:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
        try:
            def _connect_v4() -> None:
                conn.sock = open_ipv4_tcp(host, port, timeout_s)

            conn.connect = _connect_v4  # type: ignore[method-assign]
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return int(resp.status), data
        finally:
            conn.close()
