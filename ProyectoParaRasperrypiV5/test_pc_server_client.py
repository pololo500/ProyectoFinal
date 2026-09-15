"""Cliente HTTP a ServidorDePC: health, STT, chat, circuit breaker."""
from __future__ import annotations
import io
import json
import os
import time
import unittest
import wave
from pathlib import Path

import numpy as np

from unittest.mock import MagicMock, patch

from pc_server_client import (
    PcServerClient,
    open_ipv4_tcp,
    pcm_float32_to_wav_bytes,
    urlparse,
)


class TestWavBytes(unittest.TestCase):
    def test_pcm_arma_wav_16k_mono(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        audio[0] = 0.5
        raw = pcm_float32_to_wav_bytes(audio, sample_rate=16000)
        with wave.open(io.BytesIO(raw), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnframes(), 16000)


class TestHealth(unittest.TestCase):
    def test_health_200_available(self) -> None:
        calls: list[tuple[str, str]] = []

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            calls.append((method, path))
            return 200, b'{"status":"ok","stt":true,"llm":true}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertTrue(client.health())
        self.assertTrue(client.can_attempt())
        self.assertEqual(calls, [("GET", "/health")])

    def test_health_timeout_cuenta_fallo(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertFalse(client.health())
        self.assertEqual(client.fail_count, 1)
        self.assertFalse(client.circuit_open)

    def test_health_503_no_abre_circuit(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 503, b'{"status":"loading"}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertFalse(client.health())
        self.assertEqual(client.fail_count, 0)
        self.assertFalse(client.circuit_open)

    def test_health_refused_cuenta_fallo(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            raise ConnectionRefusedError("refused")

        client = PcServerClient("http://10.0.0.2:8090", "tok", request_fn=req)
        self.assertFalse(client.health())
        self.assertEqual(client.fail_count, 1)


class TestAuthAndCircuit(unittest.TestCase):
    def test_401_abre_circuit_sin_reintentar(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            return 401, b"no"

        client = PcServerClient("http://192.168.1.5:8090", "bad", request_fn=req)
        self.assertIsNone(client.transcribe(b"RIFF"))
        self.assertTrue(client.circuit_open)
        self.assertIsNone(client.transcribe(b"RIFF"))
        self.assertEqual(n["n"], 1)

    def test_dos_timeouts_abren_circuit_el_tercero_no_socketea(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.transcribe(b"x"))
        self.assertIsNone(client.complete([{"role": "user", "content": "hola"}]))
        self.assertTrue(client.circuit_open)
        self.assertEqual(n["n"], 2)
        self.assertIsNone(client.transcribe(b"x"))
        self.assertFalse(client.health())
        self.assertEqual(n["n"], 2)

    def test_health_200_cierra_circuit_tras_cooldown(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 200, b'{"status":"ok","stt":true,"llm":true}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        client.fail_count = 2
        client.open_until = time.monotonic() - 0.01
        self.assertTrue(client.health())
        self.assertFalse(client.circuit_open)
        self.assertEqual(client.fail_count, 0)


class TestTranscribeAndChat(unittest.TestCase):
    def test_transcribe_200_devuelve_texto(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/v1/audio/transcriptions")
            return 200, json.dumps({"text": "juguemos veo veo"}).encode()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertEqual(client.transcribe(b"RIFF")["text"], "juguemos veo veo")
        self.assertEqual(client.fail_count, 0)

    def test_complete_200_devuelve_content(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(path, "/v1/chat/completions")
            body = kwargs.get("body")
            self.assertIsInstance(body, bytes)
            payload = json.loads(body)
            self.assertEqual(payload["max_tokens"], 80)
            self.assertEqual(payload["messages"][0]["content"], "hola")
            return 200, json.dumps({
                "choices": [{"message": {"content": "Hola, estoy acá."}}],
            }).encode()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        out = client.complete([{"role": "user", "content": "hola"}])
        self.assertEqual(out, "Hola, estoy acá.")

    def test_sin_url_no_socketea(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            return 200, b"{}"

        client = PcServerClient("", "tok", request_fn=req)
        self.assertFalse(client.health())
        self.assertIsNone(client.transcribe(b"x"))
        self.assertEqual(n["n"], 0)


class TestFromEnv(unittest.TestCase):
    def test_from_env_usa_pc_server_url(self) -> None:
        env = {**os.environ, "PC_SERVER_URL": "http://10.1.2.3:8090", "PC_SERVER_TOKEN": "abc"}
        with patch.dict(os.environ, env, clear=True):
            client = PcServerClient.from_env()
        self.assertEqual(client.base_url, "http://10.1.2.3:8090")
        self.assertEqual(client.token, "abc")

    def test_from_env_lee_url_y_token_de_archivos(self) -> None:
        import tempfile

        root = Path(tempfile.mkdtemp())
        url_p = root / "pc_server_url.txt"
        tok_p = root / "pc_server_token.txt"
        url_p.write_text("http://192.168.0.246:8090\n", encoding="utf-8")
        tok_p.write_text("secreto-archivo\n", encoding="utf-8")
        cleaned = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PC_SERVER_URL", "PC_SERVER_TOKEN")
        }
        with patch.dict(os.environ, cleaned, clear=True):
            client = PcServerClient.from_env(cache_path=url_p, token_path=tok_p)
        self.assertEqual(client.base_url, "http://192.168.0.246:8090")
        self.assertEqual(client.token, "secreto-archivo")

    def test_health_ok_guarda_cache(self) -> None:
        cache = Path(__file__).resolve().parent / "_tmp_pc_url_cache.txt"
        if cache.exists():
            cache.unlink()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 200, b'{"status":"ok","stt":true,"llm":true}'

        try:
            client = PcServerClient(
                "http://192.168.43.10:8090",
                "tok",
                request_fn=req,
                cache_path=cache,
            )
            self.assertTrue(client.health())
            self.assertEqual(cache.read_text(encoding="utf-8").strip(), "http://192.168.43.10:8090")
        finally:
            if cache.exists():
                cache.unlink()


class TestUrlparseExport(unittest.TestCase):
    def test_urlparse_resuelve_host_puerto(self) -> None:
        parsed = urlparse("http://192.168.1.5:8090")
        self.assertEqual(parsed.hostname, "192.168.1.5")
        self.assertEqual(parsed.port, 8090)


class TestIpv4ConnectPy311(unittest.TestCase):
    def test_open_ipv4_tcp_usa_socket_af_inet_sin_family_kwarg(self) -> None:
        created: list[int] = []

        class FakeSock:
            def __init__(self) -> None:
                self.addr = None
                self.timeout = None

            def settimeout(self, value: float) -> None:
                self.timeout = value

            def connect(self, addr: tuple) -> None:
                self.addr = addr

            def close(self) -> None:
                return None

        def fake_socket(family: int, typ: int, *args: object, **kwargs: object) -> FakeSock:
            del typ, args, kwargs
            created.append(family)
            return FakeSock()

        import socket as sockmod

        with patch("pc_server_client.socket.socket", fake_socket):
            s = open_ipv4_tcp("192.168.0.246", 8090, 0.3)
        self.assertEqual(created, [sockmod.AF_INET])
        self.assertEqual(s.addr, ("192.168.0.246", 8090))
        self.assertEqual(s.timeout, 0.3)

    def test_http_request_no_usa_family_en_create_connection(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("pc_server_client.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("family=socket.AF_INET", src)
        self.assertIn("open_ipv4_tcp", src)

    def test_health_typeerror_py311_no_revienta(self) -> None:
        def boom_create(*args: object, **kwargs: object) -> object:
            raise TypeError("create_connection() got an unexpected keyword argument 'family'")

        client = PcServerClient("http://192.168.0.246:8090", "tok")
        with patch("pc_server_client.socket.create_connection", boom_create):
            with patch("pc_server_client.open_ipv4_tcp", side_effect=boom_create):
                self.assertFalse(client.health())


class TestHealthRetries(unittest.TestCase):
    def test_quinto_intento_ok_no_abre_circuit(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            del method, path, kwargs
            n["n"] += 1
            if n["n"] < 5:
                raise TimeoutError("timed out")
            return 200, b'{"status":"ok","stt":true,"llm":true}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        with patch("pc_server_client.time.sleep"):
            self.assertTrue(client.health_ready())
        self.assertEqual(n["n"], 5)
        self.assertFalse(client.circuit_open)
        self.assertEqual(client.fail_count, 0)

    def test_cinco_timeouts_cuentan_un_fallo(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            del method, path, kwargs
            n["n"] += 1
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        with patch("pc_server_client.time.sleep"):
            self.assertFalse(client.health_ready())
        self.assertEqual(n["n"], 5)
        self.assertEqual(client.fail_count, 1)
        self.assertFalse(client.circuit_open)

    def test_401_no_reintenta_cinco_veces(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            del method, path, kwargs
            n["n"] += 1
            return 401, b"no"

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        with patch("pc_server_client.time.sleep"):
            self.assertFalse(client.health_ready())
        self.assertEqual(n["n"], 1)
        self.assertTrue(client.circuit_open)


class TestTimeoutsCubrenGpuLenta(unittest.TestCase):
    def test_stt_y_llm_esperan_mas_que_el_primer_turno_real(self) -> None:
        from pc_server_client import LLM_TIMEOUT_S, STT_TIMEOUT_S

        # Medido: Whisper large-v3 frío 20.4 s; 8B decode ~10 s (17 tok).
        self.assertGreaterEqual(STT_TIMEOUT_S, 25.0)
        self.assertGreaterEqual(LLM_TIMEOUT_S, 30.0)

    def test_tts_timeout_es_10s(self) -> None:
        from pc_server_client import TTS_TIMEOUT_S

        self.assertGreaterEqual(TTS_TIMEOUT_S, 10.0)


def _tiny_wav_bytes(sr: int = 24000, n: int = 240) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class TestSynthesizeTts(unittest.TestCase):
    def test_synthesize_200_devuelve_wav(self) -> None:
        wav = _tiny_wav_bytes()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/v1/audio/speech")
            payload = json.loads(kwargs["body"])
            self.assertEqual(payload["input"], "¡Hola!")
            self.assertEqual(payload["language"], "es")
            self.assertGreaterEqual(kwargs["timeout_s"], 10.0)
            return 200, wav

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        out = client.synthesize("¡Hola!")
        self.assertEqual(out, wav)
        self.assertEqual(client.fail_count_tts, 0)
        self.assertEqual(client.fail_count, 0)

    def test_synthesize_timeout_no_toca_circuit_stt(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 1)
        self.assertEqual(client.fail_count, 0)
        self.assertFalse(client.circuit_open)
        self.assertFalse(client.circuit_tts_open)

    def test_synthesize_503_no_abre_circuit(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 503, b'{"error":"tts not ready"}'

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 0)
        self.assertFalse(client.circuit_tts_open)

    def test_synthesize_401_abre_solo_tts(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            return 401, b"no"

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertTrue(client.circuit_tts_open)
        self.assertFalse(client.circuit_open)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(n["n"], 1)

    def test_dos_timeouts_tts_el_tercero_no_socketea(self) -> None:
        n = {"n": 0}

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            n["n"] += 1
            raise TimeoutError("timed out")

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("a"))
        self.assertIsNone(client.synthesize("b"))
        self.assertTrue(client.circuit_tts_open)
        self.assertEqual(n["n"], 2)
        self.assertIsNone(client.synthesize("c"))
        self.assertEqual(n["n"], 2)

    def test_circuit_stt_abierto_no_bloquea_synthesize(self) -> None:
        wav = _tiny_wav_bytes()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(path, "/v1/audio/speech")
            return 200, wav

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        client.fail_count = 2
        client.open_until = time.monotonic() + 30.0
        self.assertTrue(client.circuit_open)
        self.assertEqual(client.synthesize("hola"), wav)

    def test_circuit_tts_abierto_no_bloquea_transcribe(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            self.assertEqual(path, "/v1/audio/transcriptions")
            return 200, json.dumps({"text": "ok"}).encode()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        client.fail_count_tts = 2
        client.open_until_tts = time.monotonic() + 30.0
        self.assertTrue(client.circuit_tts_open)
        self.assertEqual(client.transcribe(b"RIFF")["text"], "ok")

    def test_synthesize_sin_riff_cuenta_fallo_tts(self) -> None:
        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            return 200, b"not-a-wav"

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        self.assertIsNone(client.synthesize("hola"))
        self.assertEqual(client.fail_count_tts, 1)

    def test_call_concurrent_serializa(self) -> None:
        import threading

        active = {"n": 0, "max": 0}
        lock = threading.Lock()

        def req(method: str, path: str, **kwargs: object) -> tuple[int, bytes]:
            with lock:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
            time.sleep(0.05)
            with lock:
                active["n"] -= 1
            if path == "/v1/audio/speech":
                return 200, _tiny_wav_bytes()
            return 200, json.dumps({"text": "ok"}).encode()

        client = PcServerClient("http://192.168.1.5:8090", "tok", request_fn=req)
        threads = [
            threading.Thread(target=lambda: client.synthesize("a")),
            threading.Thread(target=lambda: client.transcribe(b"x")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(active["max"], 1)


if __name__ == "__main__":
    unittest.main()
