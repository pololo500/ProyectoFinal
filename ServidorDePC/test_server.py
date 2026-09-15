"""Handlers de ServidorDePC con engines fake (sin GPU)."""
from __future__ import annotations

import io
import json
import sys
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from handlers import handle_chat, handle_health, handle_speech, handle_transcribe


class FakeStt:
    def __init__(self, ready: bool = True, text: str = "juguemos veo veo") -> None:
        self.ready = ready
        self.text = text
        self.last_wav: bytes | None = None
        self.detail: dict | None = None

    def transcribe_wav(self, wav: bytes, language: str = "es") -> str | dict:
        del language
        self.last_wav = wav
        if self.detail is not None:
            return self.detail  # type: ignore[return-value]
        return self.text


class FakeLlm:
    def __init__(self, ready: bool = True, reply: str = "Hola, estoy acá.") -> None:
        self.ready = ready
        self.reply = reply
        self.last_messages: list | None = None

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.last_messages = messages
        return self.reply


class FakeTts:
    def __init__(self, ready: bool = True, wav: bytes | None = None) -> None:
        self.ready = ready
        self.wav = wav if wav is not None else _tiny_wav()
        self.last_text: str | None = None

    def synthesize(self, text: str) -> bytes:
        self.last_text = text
        return self.wav


TOKEN = "secret-token"


def _tiny_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


class TestHealth(unittest.TestCase):
    def test_503_mientras_cargan(self) -> None:
        status, body = handle_health(FakeStt(ready=False), FakeLlm(ready=True), TOKEN, "Bearer secret-token")
        self.assertEqual(status, 503)
        self.assertEqual(body["stt"], False)
        self.assertEqual(body["llm"], True)

    def test_200_cuando_ambos_listos(self) -> None:
        status, body = handle_health(FakeStt(), FakeLlm(), TOKEN, "Bearer secret-token")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["stt"])
        self.assertTrue(body["llm"])

    def test_sin_token_401(self) -> None:
        status, body = handle_health(FakeStt(), FakeLlm(), TOKEN, None)
        self.assertEqual(status, 401)
        self.assertIn("error", body)


class TestTranscribe(unittest.TestCase):
    def test_wav_devuelve_texto(self) -> None:
        stt = FakeStt()
        wav = _tiny_wav()
        status, body = handle_transcribe(
            stt, FakeLlm(), TOKEN, "Bearer secret-token", wav, "audio/wav", "es"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["text"], "juguemos veo veo")
        self.assertEqual(stt.last_wav, wav)

    def test_transcribe_sin_token_401(self) -> None:
        status, body = handle_transcribe(
            FakeStt(), FakeLlm(), TOKEN, "Bearer no", _tiny_wav(), "audio/wav", "es"
        )
        self.assertEqual(status, 401)

    def test_transcribe_loggea_llegada_y_ms(self) -> None:
        logs: list[str] = []
        wav = _tiny_wav()
        status, body = handle_transcribe(
            FakeStt(),
            FakeLlm(),
            TOKEN,
            "Bearer secret-token",
            wav,
            "audio/wav",
            "es",
            log_fn=logs.append,
            peer="192.168.0.148",
        )
        del status, body
        joined = "\n".join(logs)
        self.assertIn("192.168.0.148", joined)
        self.assertIn(f"{len(wav)} bytes", joined)
        self.assertRegex(joined, r"ms")

    def test_transcribe_incluye_confianza_si_el_engine_la_da(self) -> None:
        stt = FakeStt()
        stt.detail = {
            "text": "Qué pasa.",
            "avg_logprob": -0.2,
            "no_speech_prob": 0.88,
        }
        status, body = handle_transcribe(
            stt, FakeLlm(), TOKEN, "Bearer secret-token", _tiny_wav(), "audio/wav", "es"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["text"], "Qué pasa.")
        self.assertEqual(body["avg_logprob"], -0.2)
        self.assertEqual(body["no_speech_prob"], 0.88)


class TestChat(unittest.TestCase):
    def test_messages_devuelven_content(self) -> None:
        llm = FakeLlm()
        payload = {
            "messages": [
                {"role": "system", "content": "Sos TEO."},
                {"role": "user", "content": "hola"},
            ],
            "max_tokens": 80,
        }
        status, body = handle_chat(
            FakeStt(), llm, TOKEN, "Bearer secret-token", json.dumps(payload).encode()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["choices"][0]["message"]["content"], "Hola, estoy acá.")
        self.assertEqual(llm.last_messages[0]["role"], "system")

    def test_chat_sin_token_401(self) -> None:
        status, body = handle_chat(FakeStt(), FakeLlm(), TOKEN, "", b"{}")
        self.assertEqual(status, 401)

    def test_chat_loggea_prompt_y_ms(self) -> None:
        logs: list[str] = []
        payload = {
            "messages": [
                {"role": "system", "content": "Sos TEO."},
                {"role": "user", "content": "hola"},
            ]
        }
        status, body = handle_chat(
            FakeStt(),
            FakeLlm(),
            TOKEN,
            "Bearer secret-token",
            json.dumps(payload).encode(),
            log_fn=logs.append,
            peer="192.168.0.148",
        )
        del status, body
        joined = "\n".join(logs)
        self.assertIn("192.168.0.148", joined)
        self.assertRegex(joined, r"ms")
        self.assertIn("Hola, estoy acá.", joined)


class TestHealthTts(unittest.TestCase):
    def test_200_stt_llm_listos_tts_false(self) -> None:
        status, body = handle_health(
            FakeStt(), FakeLlm(), TOKEN, "Bearer secret-token", FakeTts(ready=False)
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["stt"])
        self.assertTrue(body["llm"])
        self.assertFalse(body["tts"])

    def test_200_tres_listos_tts_true(self) -> None:
        status, body = handle_health(
            FakeStt(), FakeLlm(), TOKEN, "Bearer secret-token", FakeTts(ready=True)
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["tts"])


class TestSpeech(unittest.TestCase):
    def test_speech_input_devuelve_wav(self) -> None:
        tts = FakeTts()
        payload = json.dumps({"input": "¡Hola! Qué lindo que estés acá.", "language": "es"}).encode()
        status, body, media = handle_speech(tts, TOKEN, "Bearer secret-token", payload)
        self.assertEqual(status, 200)
        self.assertEqual(media, "audio/wav")
        self.assertIsInstance(body, bytes)
        self.assertTrue(body.startswith(b"RIFF"))
        self.assertEqual(tts.last_text, "¡Hola! Qué lindo que estés acá.")

    def test_speech_vacio_400(self) -> None:
        status, body, media = handle_speech(
            FakeTts(), TOKEN, "Bearer secret-token", json.dumps({"input": "  "}).encode()
        )
        self.assertEqual(status, 400)
        self.assertEqual(media, "application/json")
        self.assertIn("error", body)

    def test_speech_mas_de_500_400(self) -> None:
        status, body, media = handle_speech(
            FakeTts(),
            TOKEN,
            "Bearer secret-token",
            json.dumps({"input": "a" * 501}).encode(),
        )
        self.assertEqual(status, 400)
        self.assertEqual(media, "application/json")

    def test_speech_sin_token_401(self) -> None:
        status, body, media = handle_speech(FakeTts(), TOKEN, None, b'{"input":"hola"}')
        self.assertEqual(status, 401)
        self.assertEqual(media, "application/json")

    def test_speech_no_ready_503(self) -> None:
        status, body, media = handle_speech(
            FakeTts(ready=False), TOKEN, "Bearer secret-token", b'{"input":"hola"}'
        )
        self.assertEqual(status, 503)
        self.assertEqual(media, "application/json")


class TestCoreRequirements(unittest.TestCase):
    def test_core_requirements_exclude_llama_cpp_python(self) -> None:
        """pip -r no debe resolver llama-cpp (sdist PyPI) o aborta numpy/FastAPI."""
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        install_lines = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("--"):
                continue
            pkg = line.split("#")[0].strip().lower()
            install_lines.append(pkg)
        self.assertFalse(
            any(line.startswith("llama-cpp-python") for line in install_lines),
            "llama-cpp-python no va en requirements.txt; va en requirements-llm.txt "
            "con extra-index CUDA y --only-binary para no compilar",
        )
        self.assertFalse(
            any(line.startswith("chatterbox") for line in install_lines),
            "chatterbox-tts no va en requirements.txt (TTS es Piper + Elena)",
        )

    def test_requirements_tts_piper_elena_sin_cosyvoice(self) -> None:
        text = (ROOT / "requirements-tts.txt").read_text(encoding="utf-8")
        install = "\n".join(
            raw.split("#")[0].strip().lower()
            for raw in text.splitlines()
            if raw.strip() and not raw.strip().startswith("#")
        )
        self.assertIn("piper-tts", install)
        self.assertIn("edge-tts", install)
        self.assertIn("soundfile", install)
        self.assertNotIn("chatterbox", install)
        self.assertNotIn("wetext", install)
        self.assertNotIn("cosyvoice", install)
        self.assertNotIn("lightning", install)

    def test_run_ps1_no_clona_cosyvoice(self) -> None:
        text = (ROOT / "run.ps1").read_text(encoding="utf-8")
        self.assertNotIn("FunAudioLLM/CosyVoice", text)
        self.assertNotIn("git clone --recursive", text)
        self.assertIn("requirements-tts.txt", text)

    def test_gitignore_prefer_elena(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8").replace("\\", "/")
        self.assertIn("tts_prefer_elena.txt", text)
        self.assertIn("third_party/CosyVoice/", text)
        self.assertIn("pretrained_models/", text)

    def test_gitignore_voices_wav(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("voices/*.wav", text.replace("\\", "/"))


class TestLlmDefaults(unittest.TestCase):
    def test_default_es_gemma3_12b_q5(self) -> None:
        import config as cfg

        self.assertIn("gemma-3-12b-it", cfg.LLM_GGUF)
        self.assertIn("Q5_K_M", cfg.LLM_GGUF)
        self.assertIn("google_gemma-3-12b-it-GGUF", cfg.LLM_REPO)
        self.assertIn("<end_of_turn>", cfg.LLM_STOP)


class TestHealthHttp(unittest.TestCase):
    def test_get_health_con_bearer_no_es_422(self) -> None:
        import server as srv
        from fastapi.testclient import TestClient

        srv.stt_engine.ready = True
        srv.llm_engine.ready = True
        client = TestClient(srv.create_app())
        resp = client.get(
            "/health",
            headers={"Authorization": f"Bearer {srv.TOKEN}"},
        )
        self.assertNotEqual(
            resp.status_code,
            422,
            msg=f"FastAPI rechazó /health: {resp.text}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        self.assertIn("tts", resp.json())


class TestPreferElena(unittest.TestCase):
    def test_default_true_sin_env_ni_archivo(self) -> None:
        from config import prefer_elena

        missing = ROOT / "no-existe-prefer-elena.txt"
        self.assertTrue(prefer_elena(env={}, path=missing))

    def test_env_false_gana_sobre_archivo(self) -> None:
        import tempfile

        from config import prefer_elena

        path = Path(tempfile.mkdtemp()) / "tts_prefer_elena.txt"
        path.write_text("true\n", encoding="utf-8")
        self.assertFalse(prefer_elena(env={"PC_TTS_PREFER_ELENA": "false"}, path=path))

    def test_archivo_false_si_no_hay_env(self) -> None:
        import tempfile

        from config import prefer_elena

        path = Path(tempfile.mkdtemp()) / "tts_prefer_elena.txt"
        path.write_text("off\n", encoding="utf-8")
        self.assertFalse(prefer_elena(env={}, path=path))

    def test_env_on_es_true(self) -> None:
        from config import prefer_elena

        self.assertTrue(prefer_elena(env={"PC_TTS_PREFER_ELENA": "ON"}, path=ROOT / "nope.txt"))

    def test_valor_raro_cae_a_true(self) -> None:
        from config import prefer_elena

        self.assertTrue(prefer_elena(env={"PC_TTS_PREFER_ELENA": "maybe"}, path=ROOT / "nope.txt"))


class TestPrepareTtsText(unittest.TestCase):
    def test_agrega_punto_si_falta(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text("hola"), "hola.")

    def test_no_toca_exclamacion(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text("¡Hola!"), "¡Hola!")

    def test_no_toca_pregunta(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text("¿Todo bien?"), "¿Todo bien?")

    def test_no_toca_puntos_suspensivos(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text("hola…"), "hola…")

    def test_colapsa_espacios(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text("hola   che"), "hola che.")

    def test_vacio_sigue_vacio(self) -> None:
        from tts_elena import prepare_tts_text

        self.assertEqual(prepare_tts_text(""), "")
        self.assertEqual(prepare_tts_text("   "), "")

    def test_voz_y_timeout(self) -> None:
        from tts_elena import ELENA_TIMEOUT_S, VOICE_NAME, VOICE_RATE

        self.assertEqual(VOICE_NAME, "es-AR-ElenaNeural")
        self.assertEqual(VOICE_RATE, "-8%")
        self.assertEqual(ELENA_TIMEOUT_S, 6.0)


class TestFloatToWav(unittest.TestCase):
    def test_riff_16bit_mono(self) -> None:
        import numpy as np

        from tts_wav import float_to_wav_bytes

        wav = float_to_wav_bytes(np.array([0.0, 0.5, -0.5], dtype=np.float32), 16000)
        self.assertTrue(wav.startswith(b"RIFF"))
        with wave.open(io.BytesIO(wav), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnframes(), 3)


class TestElenaSynthesize(unittest.TestCase):
    def test_factory_y_decode_dan_wav(self) -> None:
        import numpy as np

        from tts_elena import VOICE_NAME, VOICE_RATE, synthesize_wav

        calls: list[tuple] = []

        class FakeCommunicate:
            def __init__(self, text: str, voice: str, rate: str = "-8%") -> None:
                calls.append((text, voice, rate))

            async def save(self, path: str) -> None:
                Path(path).write_bytes(b"ID3FAKE")

        def decode_mp3(mp3: bytes):
            self.assertEqual(mp3, b"ID3FAKE")
            return np.array([0.1, -0.1, 0.2], dtype=np.float32), 16000

        wav = synthesize_wav(
            "hola",
            communicate_factory=FakeCommunicate,
            decode_mp3=decode_mp3,
        )
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(calls, [("hola.", VOICE_NAME, VOICE_RATE)])
        with wave.open(io.BytesIO(wav), "rb") as wf:
            self.assertEqual(wf.getframerate(), 16000)
            self.assertEqual(wf.getnframes(), 3)

    def test_vacio_no_llama_factory(self) -> None:
        from tts_elena import synthesize_wav

        class Boom:
            def __init__(self, *args, **kwargs) -> None:
                raise AssertionError("no debía llamarse")

        self.assertEqual(synthesize_wav("   ", communicate_factory=Boom), b"")

    def test_decode_vacio_devuelve_vacio(self) -> None:
        from tts_elena import synthesize_wav

        class FakeCommunicate:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def save(self, path: str) -> None:
                Path(path).write_bytes(b"x")

        wav = synthesize_wav(
            "hola",
            communicate_factory=FakeCommunicate,
            decode_mp3=lambda _mp3: (None, 0),
        )
        self.assertEqual(wav, b"")

    def test_timeout_devuelve_vacio(self) -> None:
        import asyncio
        import time

        from tts_elena import synthesize_wav

        class SlowCommunicate:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def save(self, path: str) -> None:
                await asyncio.sleep(2)
                Path(path).write_bytes(b"x")

        t0 = time.monotonic()
        wav = synthesize_wav(
            "hola",
            timeout_s=0.05,
            communicate_factory=SlowCommunicate,
            decode_mp3=lambda _mp3: (None, 0),
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(wav, b"")
        self.assertLess(elapsed, 0.5, f"timeout bloqueó {elapsed:.2f}s esperando el hilo")


class TestPiperEngine(unittest.TestCase):
    def test_constantes_dialogo(self) -> None:
        from tts_piper import PiperEngine

        self.assertEqual(PiperEngine.MODEL_NAME, "es_AR-daniela-high")
        self.assertEqual(PiperEngine.MODEL_HF_PATH, "es/es_AR/daniela/high")
        self.assertEqual(PiperEngine.LENGTH_SCALE, 1.20)
        self.assertEqual(PiperEngine.NOISE_SCALE, 0.667)
        self.assertEqual(PiperEngine.NOISE_W_SCALE, 0.98)

    def test_load_con_voz_inyectada_marca_ready(self) -> None:
        from tts_piper import PiperEngine

        engine = PiperEngine(voice=_FakePiperVoice())
        self.assertFalse(engine.ready)
        engine.load()
        self.assertTrue(engine.ready)

    def test_load_falla_sin_ready(self) -> None:
        from tts_piper import PiperEngine

        def boom(_path: str):
            raise OSError("sin modelo")

        engine = PiperEngine(voice_loader=boom, ensure_model=lambda: Path("fake.onnx"))
        engine.load()
        self.assertFalse(engine.ready)
        self.assertEqual(engine.synthesize("hola"), b"")

    def test_synthesize_une_chunks_y_pasa_escalas(self) -> None:
        import numpy as np

        from tts_piper import PiperEngine

        voice = _FakePiperVoice()
        engine = PiperEngine(voice=voice)
        engine.load()
        wav = engine.synthesize("hola che")
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(voice.last_text, "hola che")
        self.assertAlmostEqual(voice.last_config.length_scale, 1.20)
        self.assertAlmostEqual(voice.last_config.noise_scale, 0.667)
        self.assertAlmostEqual(voice.last_config.noise_w_scale, 0.98)
        with wave.open(io.BytesIO(wav), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 22050)
            self.assertEqual(wf.getnframes(), 4)

    def test_texto_vacio_es_silencio(self) -> None:
        from tts_piper import PiperEngine

        engine = PiperEngine(voice=_FakePiperVoice())
        engine.load()
        self.assertEqual(engine.synthesize("  "), b"")


class _FakePiperChunk:
    def __init__(self, audio, sample_rate: int) -> None:
        self.audio_float_array = audio
        self.sample_rate = sample_rate


class _FakePiperVoice:
    def __init__(self) -> None:
        self.last_text: str | None = None
        self.last_config = None

    def synthesize(self, text: str, syn_config=None):
        import numpy as np

        self.last_text = text
        self.last_config = syn_config
        yield _FakePiperChunk(np.array([0.1, 0.2], dtype=np.float32), 22050)
        yield _FakePiperChunk(np.array([-0.1, -0.2], dtype=np.float32), 22050)


class _FakePiperReady:
    def __init__(self, wav: bytes = b"PIPERWAV", load_ready: bool = True) -> None:
        self._wav = wav
        self._load_ready = load_ready
        self.ready = False
        self.calls: list[str] = []

    def load(self) -> None:
        self.ready = self._load_ready

    def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        return self._wav


class TestTtsRouting(unittest.TestCase):
    def test_prefer_false_no_llama_elena(self) -> None:
        from tts_engine import TtsEngine

        elena_calls: list[str] = []

        def elena(text: str) -> bytes:
            elena_calls.append(text)
            return b"ELENA"

        piper = _FakePiperReady()
        engine = TtsEngine(piper=piper, elena_fn=elena, prefer_fn=lambda: False)
        engine.load()
        self.assertTrue(engine.ready)
        self.assertEqual(engine.synthesize("hola"), b"PIPERWAV")
        self.assertEqual(elena_calls, [])
        self.assertEqual(piper.calls, ["hola"])

    def test_prefer_true_elena_ok(self) -> None:
        from tts_engine import TtsEngine

        piper = _FakePiperReady()
        engine = TtsEngine(
            piper=piper, elena_fn=lambda _t: b"ELENAWAV", prefer_fn=lambda: True
        )
        engine.load()
        self.assertEqual(engine.synthesize("hola"), b"ELENAWAV")
        self.assertEqual(piper.calls, [])

    def test_prefer_true_elena_vacio_cae_piper(self) -> None:
        from tts_engine import TtsEngine

        piper = _FakePiperReady()
        engine = TtsEngine(piper=piper, elena_fn=lambda _t: b"", prefer_fn=lambda: True)
        engine.load()
        self.assertEqual(engine.synthesize("hola"), b"PIPERWAV")
        self.assertEqual(piper.calls, ["hola"])

    def test_prefer_true_elena_error_cae_piper(self) -> None:
        from tts_engine import TtsEngine

        def boom(_text: str) -> bytes:
            raise RuntimeError("sin red")

        piper = _FakePiperReady()
        engine = TtsEngine(piper=piper, elena_fn=boom, prefer_fn=lambda: True)
        engine.load()
        self.assertEqual(engine.synthesize("hola"), b"PIPERWAV")

    def test_texto_vacio_es_silencio(self) -> None:
        from tts_engine import TtsEngine

        piper = _FakePiperReady()
        engine = TtsEngine(
            piper=piper, elena_fn=lambda _t: b"ELENA", prefer_fn=lambda: True
        )
        engine.load()
        self.assertEqual(engine.synthesize("  "), b"")
        self.assertEqual(piper.calls, [])

    def test_piper_ausente_ready_false(self) -> None:
        from tts_engine import TtsEngine

        piper = _FakePiperReady(load_ready=False)
        engine = TtsEngine(
            piper=piper, elena_fn=lambda _t: b"", prefer_fn=lambda: False
        )
        engine.load()
        self.assertFalse(engine.ready)
        self.assertEqual(engine.synthesize("hola"), b"")


if __name__ == "__main__":
    unittest.main()
