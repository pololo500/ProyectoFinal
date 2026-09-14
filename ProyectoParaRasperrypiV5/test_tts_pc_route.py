"""SpeechWorker: TTS de ServidorDePC con fallback Piper."""
from __future__ import annotations

import io
import time
import unittest
import wave
from unittest.mock import MagicMock, patch

import numpy as np

from workers import SpeechWorker


def _tiny_wav_bytes(sr: int = 24000, n: int = 240) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class FakePcClient:
    def __init__(self, wav: bytes | None = None, attempt: bool = True) -> None:
        self.wav = wav if wav is not None else _tiny_wav_bytes()
        self.attempt = attempt
        self.texts: list[str] = []
        self.times: list[float] = []
        self.fail_texts: set[str] = set()

    def can_attempt_tts(self) -> bool:
        return self.attempt

    def synthesize(self, text: str) -> bytes | None:
        self.texts.append(text)
        self.times.append(time.monotonic())
        if text in self.fail_texts:
            return None
        return self.wav


class TestWavBytesToPcm(unittest.TestCase):
    def test_decodifica_24k_mono(self) -> None:
        wav = _tiny_wav_bytes(24000, 240)
        out = SpeechWorker._wav_bytes_to_pcm(wav)
        self.assertIsNotNone(out)
        audio, sr = out
        self.assertEqual(sr, 24000)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.size, 240)

    def test_invalido_none(self) -> None:
        self.assertIsNone(SpeechWorker._wav_bytes_to_pcm(b"nope"))


class TestSpeakPcTts(unittest.TestCase):
    def test_pc_200_reproduce_sin_piper(self) -> None:
        client = FakePcClient()
        worker = SpeechWorker(output_device_index=0, pc_client=client)
        worker._piper_voice = object()
        plays: list[tuple] = []
        piper_called = {"n": 0}

        def piper(*args: object, **kwargs: object):
            piper_called["n"] += 1
            return (np.zeros(8, dtype=np.float32), 22050)

        with patch.object(worker, "_play_wav_via_output_stream", side_effect=lambda *a, **k: plays.append((a, k))), patch.object(
            worker, "_synthesize_piper_pcm", side_effect=piper
        ):
            worker._speak_queued_text("Hola.")
        self.assertEqual(client.texts, ["Hola."])
        self.assertEqual(len(plays), 1)
        self.assertEqual(piper_called["n"], 0)

    def test_pc_none_usa_piper(self) -> None:
        client = FakePcClient()
        client.fail_texts.add("Hola.")
        worker = SpeechWorker(output_device_index=0, pc_client=client)
        worker._piper_voice = object()
        piper_called = {"n": 0}

        def piper(text: str, length_scale: float | None = None):
            piper_called["n"] += 1
            return (np.zeros(8, dtype=np.float32), 22050)

        with patch.object(worker, "_play_wav_via_output_stream"), patch.object(
            worker, "_synthesize_piper_pcm", side_effect=piper
        ):
            worker._speak_queued_text("Hola.")
        self.assertEqual(piper_called["n"], 1)

    def test_circuit_tts_cerrado_cero_http(self) -> None:
        client = FakePcClient(attempt=False)
        worker = SpeechWorker(output_device_index=0, pc_client=client)
        worker._piper_voice = object()

        def piper(text: str, length_scale: float | None = None):
            return (np.zeros(8, dtype=np.float32), 22050)

        with patch.object(worker, "_play_wav_via_output_stream"), patch.object(
            worker, "_synthesize_piper_pcm", side_effect=piper
        ):
            worker._speak_queued_text("Hola.")
        self.assertEqual(client.texts, [])

    def test_cloud_mode_cero_synthesize(self) -> None:
        client = FakePcClient()
        cloud = MagicMock()
        worker = SpeechWorker(
            output_device_index=0, pc_client=client, cloud_mode=True, cloud_tts=cloud
        )
        with patch.object(worker, "_speak_cloud") as cloud_speak:
            worker._speak_queued_text("Hola.")
        cloud_speak.assert_called_once()
        self.assertEqual(client.texts, [])

    def test_cuento_segunda_falla_piper_tercera_reintenta_pc(self) -> None:
        client = FakePcClient()
        client.fail_texts.add("Dos.")
        worker = SpeechWorker(output_device_index=0, pc_client=client)
        worker._piper_voice = object()
        piper_texts: list[str] = []
        play_end: list[float] = []

        def play(*args: object, **kwargs: object) -> None:
            time.sleep(0.05)
            play_end.append(time.monotonic())

        def piper(text: str, length_scale: float | None = None):
            piper_texts.append(text)
            self.assertEqual(length_scale, SpeechWorker.PIPER_STORY_LENGTH_SCALE)
            return (np.zeros(8, dtype=np.float32), 22050)

        with patch.object(worker, "_play_wav_via_output_stream", side_effect=play), patch.object(
            worker, "_synthesize_piper_pcm", side_effect=piper
        ):
            worker._speak_sentence_pipeline(["Uno.", "Dos.", "Tres."])
        self.assertEqual(client.texts, ["Uno.", "Dos.", "Tres."])
        self.assertEqual(piper_texts, ["Dos."])
        self.assertGreaterEqual(len(play_end), 1)
        self.assertLess(client.times[1], play_end[0])


if __name__ == "__main__":
    unittest.main()
