"""AudioWorker: STT/LLM vía PC con fallback local (sin cloud_mode)."""
from __future__ import annotations

import queue
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

import numpy as np

from workers import AudioWorker, TranscriptionResult


class FakePc:
    def __init__(
        self,
        *,
        health_ok: bool = True,
        circuit_open: bool = False,
        stt: str | dict | None = "juguemos veo veo",
        llm: str | None = "Hola desde la PC.",
    ) -> None:
        self._health_ok = health_ok
        self.circuit_open = circuit_open
        self.stt = stt
        self.llm = llm
        self.transcribe_calls = 0
        self.complete_calls = 0
        self.health_calls = 0
        self.base_url = "http://192.168.1.5:8090"
        self.token = "tok"

    def can_attempt(self) -> bool:
        return (not self.circuit_open) and True

    def health(self) -> bool:
        self.health_calls += 1
        return self._health_ok and not self.circuit_open

    def health_ready(self, attempts: int = 5, **kwargs: object) -> bool:
        del kwargs
        for _ in range(max(1, attempts)):
            if self.health():
                return True
        return False

    def transcribe(self, wav: bytes) -> str | dict | None:
        del wav
        self.transcribe_calls += 1
        return self.stt

    def complete(self, messages: list) -> str | None:
        del messages
        self.complete_calls += 1
        return self.llm


class FakeLocalLlm:
    is_available = True

    def generate(self, text: str, emotion=None, history=None) -> str:
        del emotion, history
        return f"3b:{text[:12]}"


def _worker(pc: FakePc | None = None, local: FakeLocalLlm | None = None) -> AudioWorker:
    worker = AudioWorker.__new__(AudioWorker)
    worker.cloud_mode = False
    worker.pc_client = pc
    worker.fallback_llm = local if local is not None else FakeLocalLlm()
    worker._preprocess_audio = lambda audio: audio
    worker._transcribe = lambda model, audio: TranscriptionResult(text="stt local")
    return worker


class TestPcReady(unittest.TestCase):
    def test_health_ok(self) -> None:
        pc = FakePc(health_ok=True)
        self.assertTrue(_worker(pc)._pc_ready_this_turn())
        self.assertEqual(pc.health_calls, 1)

    def test_circuit_open_no_health(self) -> None:
        pc = FakePc(health_ok=True, circuit_open=True)
        self.assertFalse(_worker(pc)._pc_ready_this_turn())
        self.assertEqual(pc.health_calls, 0)

    def test_sin_cliente(self) -> None:
        worker = _worker(None)
        self.assertFalse(worker._pc_ready_this_turn())
        self.assertIn("cliente", worker._pc_skip_reason)

    def test_sin_url_loggea_omitido(self) -> None:
        pc = FakePc()
        pc.base_url = ""
        worker = _wired_worker(pc)
        self.assertFalse(worker._pc_ready_this_turn())
        self.assertIn("URL", worker._pc_skip_reason)
        worker._log_pc(f"[PC] omitido: {worker._pc_skip_reason}")
        joined = "\n".join(_drain_logs(worker))
        self.assertIn("[PC] omitido", joined)
        self.assertIn("URL", joined)

    def test_health_typeerror_no_tumba_el_turno(self) -> None:
        pc = FakePc()

        def boom() -> bool:
            raise TypeError("create_connection() got an unexpected keyword argument 'family'")

        pc.health = boom  # type: ignore[method-assign]
        worker = _worker(pc)
        self.assertFalse(worker._pc_ready_this_turn())
        self.assertIn("health", worker._pc_skip_reason)

    def test_health_ok_tras_reintentos(self) -> None:
        pc = FakePc(health_ok=False)
        n = {"i": 0}

        def ready(*, attempts: int = 5, **kwargs: object) -> bool:
            del kwargs
            for _ in range(attempts):
                n["i"] += 1
                pc.health_calls += 1
                if n["i"] >= 5:
                    return True
            return False

        pc.health_ready = ready  # type: ignore[method-assign]
        self.assertTrue(_worker(pc)._pc_ready_this_turn())
        self.assertEqual(n["i"], 5)


class TestSttRoute(unittest.TestCase):
    def test_pc_ok_usa_texto_remoto(self) -> None:
        pc = FakePc(stt="juguemos veo veo")
        worker = _worker(pc)
        out = worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=True)
        self.assertEqual(out.text, "juguemos veo veo")
        self.assertEqual(pc.transcribe_calls, 1)

    def test_pc_stt_marca_baja_confianza_con_no_speech(self) -> None:
        pc = FakePc(
            stt={  # type: ignore[arg-type]
                "text": "Qué pasa.",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.88,
            }
        )
        worker = _worker(pc)
        out = worker._remote_or_local_stt(
            np.zeros(1600, dtype=np.float32), object(), pc_ready=True
        )
        self.assertEqual(out.text, "Qué pasa.")
        self.assertTrue(out.low_confidence)
        self.assertEqual(out.no_speech_prob, 0.88)

    def test_pc_fail_usa_local(self) -> None:
        pc = FakePc(stt=None)
        worker = _worker(pc)
        out = worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=True)
        self.assertEqual(out.text, "stt local")
        self.assertEqual(pc.transcribe_calls, 1)

    def test_pc_not_ready_usa_local(self) -> None:
        pc = FakePc()
        worker = _worker(pc)
        out = worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=False)
        self.assertEqual(out.text, "stt local")
        self.assertEqual(pc.transcribe_calls, 0)


class TestLlmRoute(unittest.TestCase):
    def test_pc_ok_usa_8b(self) -> None:
        pc = FakePc(llm="Hola desde la PC.")
        worker = _worker(pc)
        out = worker._remote_or_local_llm("como estas", None, [], pc_ready=True)
        self.assertEqual(out, "Hola desde la PC.")
        self.assertEqual(pc.complete_calls, 1)

    def test_pc_fail_usa_3b(self) -> None:
        pc = FakePc(llm=None)
        worker = _worker(pc)
        out = worker._remote_or_local_llm("como estas", None, [], pc_ready=True)
        self.assertTrue(out.startswith("3b:"))
        self.assertEqual(pc.complete_calls, 1)

    def test_stt_local_igual_puede_llamar_8b(self) -> None:
        pc = FakePc(stt=None, llm="ocho B")
        worker = _worker(pc)
        stt = worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=True)
        self.assertEqual(stt.text, "stt local")
        reply = worker._remote_or_local_llm("zanahoria", None, [], pc_ready=True)
        self.assertEqual(reply, "ocho B")


def _wired_worker(pc: FakePc | None = None) -> AudioWorker:
    worker = _worker(pc)
    worker.message_queue = queue.Queue()
    worker.message_semaphore = threading.Semaphore(20)
    return worker


def _drain_logs(worker: AudioWorker) -> list[str]:
    out: list[str] = []
    q = worker.message_queue
    while True:
        try:
            msg = q.get_nowait()
        except queue.Empty:
            break
        if msg.kind == "log":
            out.append(str(msg.payload))
    return out


class TestPcConsoleLogs(unittest.TestCase):
    def test_stt_loggea_envio_a_pc(self) -> None:
        pc = FakePc(stt="juguemos veo veo")
        worker = _wired_worker(pc)
        worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=True)
        joined = "\n".join(_drain_logs(worker))
        self.assertIn("[PC]", joined)
        self.assertIn("enviando", joined.lower())
        self.assertIn("192.168.1.5:8090", joined)
        self.assertIn("STT", joined)
        self.assertRegex(joined, r"ms")

    def test_llm_loggea_envio_a_pc(self) -> None:
        pc = FakePc(llm="Hola desde la PC.")
        worker = _wired_worker(pc)
        worker._remote_or_local_llm("como estas", None, [], pc_ready=True)
        joined = "\n".join(_drain_logs(worker))
        self.assertIn("[PC]", joined)
        self.assertIn("enviando", joined.lower())
        self.assertIn("LLM", joined)
        self.assertRegex(joined, r"ms")

    def test_stt_fallo_loggea_fallback_local(self) -> None:
        pc = FakePc(stt=None)
        worker = _wired_worker(pc)
        worker._remote_or_local_stt(np.zeros(1600, dtype=np.float32), object(), pc_ready=True)
        joined = "\n".join(_drain_logs(worker))
        self.assertIn("[PC]", joined)
        self.assertRegex(joined.lower(), r"fall|local")


class TestHandleSegmentWiring(unittest.TestCase):
    def test_handle_segment_usa_pc_y_no_cloud_mode(self) -> None:
        from pathlib import Path

        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(encoding="utf-8")
        start = src.index("def _handle_segment")
        end = src.index("def _silence_mic_after_speaker", start) if "def _silence_mic_after_speaker" in src[start:] else start + 40000
        # _handle_segment is long; slice until next def at similar indent after a marker
        body = src[start:start + 25000]
        self.assertIn("_pc_ready_this_turn", body)
        self.assertIn("_remote_or_local_stt", body)
        self.assertIn("_remote_or_local_llm", body)
        self.assertIn("STT_PC", src)
        self.assertIn("LLM_PC", src)


if __name__ == "__main__":
    unittest.main()
