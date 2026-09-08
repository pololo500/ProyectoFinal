"""Micrófono USB local: negociar sample rate (PaErrorCode -9997) y sin puente TCP."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from workers import (
    AUDIO_QUEUE_MAXSIZE,
    AudioWorker,
    EmotionReactor,
    apply_capture_drops,
    capture_hop_seconds,
    downsample_capture_to_stt,
    enqueue_mic_block,
    find_supported_input_config,
    mic_block_to_stt,
    pcm_s16le_to_float32,
    pi_mic_capture_rate,
    stt_block_duration_seconds,
    vad_circular_maxlen,
    vad_log_label,
    vad_pre_roll_blocks,
)


class _Unsupported(Exception):
    pass


def _check_usb_pnp(**kwargs):
    """USB PnP típico: no abre a 16 kHz (el error de la captura)."""
    if kwargs.get("samplerate") not in (44100.0, 48000.0):
        raise _Unsupported("Invalid sample rate [PaErrorCode -9997]")
    if kwargs.get("channels") not in (1, 2):
        raise _Unsupported("Invalid number of channels")


class TestFindSupportedInputConfig(unittest.TestCase):
    def test_usb_pnp_elige_48k_si_16k_falla(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 48000.0}
        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", side_effect=_check_usb_pnp
        ):
            sr, dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(sr, 48000)
        self.assertEqual(channels, 1)
        self.assertEqual(dtype, "float32")

    def test_si_16k_anda_lo_deja(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 16000.0}
        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", return_value=None
        ):
            sr, dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(sr, 16000)
        self.assertEqual(dtype, "float32")
        self.assertEqual(channels, 1)

    def test_no_pide_mas_canales_que_el_dispositivo(self) -> None:
        info = {"max_input_channels": 1, "default_samplerate": 44100.0}
        seen: list[int] = []

        def _check(**kwargs):  # noqa: ANN003
            ch = int(kwargs.get("channels") or 0)
            seen.append(ch)
            if ch > 1:
                raise AssertionError("ALSA: channelCount <= maxChans")
            if kwargs.get("samplerate") == 16000.0:
                raise _Unsupported("Invalid sample rate")

        with patch("workers.sd.query_devices", return_value=info), patch(
            "workers.sd.check_input_settings", side_effect=_check
        ):
            sr, _dtype, channels = find_supported_input_config(0, preferred_sr=16000)
        self.assertEqual(channels, 1)
        self.assertEqual(sr, 44100)
        self.assertTrue(seen)
        self.assertTrue(all(ch <= 1 for ch in seen))


class TestMicBlockToStt(unittest.TestCase):
    def test_bloque_48k_queda_en_16k(self) -> None:
        frames_48k = int(48000 * 0.128)
        indata = np.zeros((frames_48k, 1), dtype=np.float32)
        out = mic_block_to_stt(indata, capture_sr=48000, target_sr=16000)
        self.assertEqual(len(out), int(16000 * 0.128))
        self.assertEqual(out.dtype, np.float32)

    def test_int16_estereo_pasa_a_float_mono(self) -> None:
        frames = 100
        stereo = np.zeros((frames, 2), dtype=np.int16)
        stereo[:, 0] = 16384
        out = mic_block_to_stt(stereo, capture_sr=16000, target_sr=16000)
        self.assertEqual(len(out), frames)
        self.assertAlmostEqual(float(out[0]), 0.5, delta=0.01)


class TestPiMicFijo(unittest.TestCase):
    def test_linux_abre_el_usb_a_48k(self) -> None:
        with patch("workers.sys.platform", "linux"):
            self.assertEqual(pi_mic_capture_rate(), 48000)

    def test_windows_sigue_en_16k(self) -> None:
        with patch("workers.sys.platform", "win32"):
            self.assertEqual(pi_mic_capture_rate(), 16000)

    def test_48k_a_16k_promedia_grupos_de_tres(self) -> None:
        x = np.arange(12, dtype=np.float32)
        out = downsample_capture_to_stt(x, 48000, 16000)
        expected = np.array([1.0, 4.0, 7.0, 10.0], dtype=np.float32)
        np.testing.assert_allclose(out, expected, rtol=0, atol=1e-6)
        np.testing.assert_raises(
            AssertionError,
            np.testing.assert_array_equal,
            out,
            np.array([0, 3, 6, 9], dtype=np.float32),
        )

    def test_audio_worker_no_reesamplea_en_el_callback(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mic_block_to_stt(indata", src)
        self.assertIn("pi_mic_capture_rate()", src)
        self.assertIn("downsample_capture_to_stt(", src)
        alsa = Path(__file__).resolve().parent.joinpath("alsa_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("downsample_capture_to_stt", alsa)
        self.assertNotIn("SpeechWorker._resample_audio", alsa)


class TestVadHopReal(unittest.TestCase):
    def test_linux_hop_es_20ms(self) -> None:
        self.assertAlmostEqual(capture_hop_seconds("linux"), 0.020)

    def test_windows_hop_sigue_128ms(self) -> None:
        self.assertAlmostEqual(capture_hop_seconds("win32"), 0.128)

    def test_pre_roll_y_circular_con_20ms(self) -> None:
        self.assertEqual(vad_pre_roll_blocks(0.020), 50)
        self.assertEqual(vad_circular_maxlen(0.020), 300)

    def test_pre_roll_y_circular_con_128ms(self) -> None:
        self.assertEqual(vad_pre_roll_blocks(0.128), 8)
        self.assertEqual(vad_circular_maxlen(0.128), 47)

    def test_duracion_320_samples_16k(self) -> None:
        self.assertAlmostEqual(stt_block_duration_seconds(320, 16000), 0.020)

    def test_duracion_2048_samples_16k(self) -> None:
        self.assertAlmostEqual(stt_block_duration_seconds(2048, 16000), 0.128)

    def test_int16_a_float_simetrico(self) -> None:
        x = np.array([0, 32767, -32768], dtype=np.int16)
        out = pcm_s16le_to_float32(x)
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out[0]), 0.0, delta=1e-6)
        self.assertGreater(float(out[1]), 0.99)
        self.assertLess(float(out[2]), -0.99)

    def test_listen_suma_duracion_real_no_0128(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("silence_seconds += block_duration_seconds", src)
        self.assertIn("stt_block_duration_seconds(", src)
        self.assertIn("pcm_s16le_to_float32(", src)


class TestNoPuenteMicPc(unittest.TestCase):
    def test_cli_no_tiene_mic_tcp(self) -> None:
        from app import build_arg_parser

        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--mic-tcp"])

    def test_workers_no_abre_tcp_de_la_pc(self) -> None:
        src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mic_tcp", src)
        self.assertNotIn("run_mic_tcp_server", src)


_WORKERS = Path(__file__).resolve().parent.joinpath("workers.py")


class TestMicHalfDuplex(unittest.TestCase):
    """El drain/callback no loguea. La captura sigue viva durante Whisper/LLM."""

    def test_callback_no_loguea_overflow(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertFalse(
            'f"Audio callback: {status}"' in src or "Audio callback:" in src,
            "el callback no debe loguear status (PortAudio no puede esperar al GIL)",
        )
        alsa = Path(__file__).resolve().parent.joinpath("alsa_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("log_action", alsa)
        self.assertNotIn("_queue_message", alsa)
        self.assertNotIn("session_policy", alsa)

    def test_captura_sigue_viva_durante_whisper_y_llm(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertNotIn("mic cerrado para STT/LLM", src)
        self.assertIn("set_muted", src)
        self.assertIn("AlsaCapture", src)
        listen_at = src.find("def listen_until_cut")
        handle_at = src.find("self._handle_segment(segment,")
        self.assertGreater(listen_at, 0)
        self.assertGreater(handle_at, listen_at)
        between = src[listen_at:handle_at]
        self.assertIn("return segment_audio", between)
        self.assertNotIn("with sd.InputStream(", between)
        self.assertNotIn("capture.stop(", between)
        self.assertNotIn("._proc.kill", between)
        after_handle = src[handle_at : handle_at + 800]
        # mute around STT/LLM, drain cola VAD, no matar arecord
        before_handle = src[handle_at - 500 : handle_at]
        self.assertIn("set_muted(True)", before_handle)
        self.assertIn("_drain_audio_queue", before_handle)

    def test_whisper_prompt_no_inyecta_que_es_eso(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertFalse(
            "¿Qué es eso?" in src,
            "el prompt de Whisper no debe incluir '¿Qué es eso?' (alucina esa frase)",
        )

    def test_callback_windows_no_importa_session_policy(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        cb_at = src.find("def callback(")
        if cb_at < 0:
            return
        # callback corto: hasta listen_until_cut o AlsaCapture
        chunk = src[cb_at : cb_at + 900]
        self.assertNotIn("from session_policy import mic_open_for_listen", chunk)

    def test_alsa_stats_usan_delta_por_utterance(self) -> None:
        """restarts/busy_hits son acumulativos; loguear solo el delta de esta escucha."""
        import re

        src = _WORKERS.read_text(encoding="utf-8")
        listen_at = src.find("segment = listen_until_cut()")
        self.assertGreater(listen_at, 0)
        before = src[max(0, listen_at - 600) : listen_at]
        after = src[listen_at : listen_at + 400]
        self.assertIn("overrun_before", before)
        self.assertIn("restart_before", before)
        self.assertIn("busy_before", before)
        self.assertIn("capture.restarts - restart_before", after)
        self.assertIn("capture.busy_hits - busy_before", after)
        self.assertIsNone(
            re.search(r"n_restart = capture\.restarts\s*$", after, re.MULTILINE),
            "n_restart debe ser delta, no total acumulado",
        )
        self.assertIsNone(
            re.search(r"n_busy = capture\.busy_hits\s*$", after, re.MULTILINE),
            "n_busy debe ser delta, no total acumulado",
        )


class TestEndpointingYCola(unittest.TestCase):
    def test_silencio_normal_es_1_2(self) -> None:
        self.assertAlmostEqual(EmotionReactor.NORMAL_SILENCE, 1.2)
        self.assertAlmostEqual(EmotionReactor.EXTENDED_SILENCE, 3.0)

    def test_max_listen_es_8(self) -> None:
        self.assertAlmostEqual(AudioWorker.MAX_LISTEN_SECONDS, 8.0)

    def test_cola_de_captura_es_128(self) -> None:
        self.assertEqual(AUDIO_QUEUE_MAXSIZE, 128)
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn(
            "audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)",
            src,
        )

    def test_enqueue_cuenta_bloques_descartados(self) -> None:
        import queue

        q: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
        drops = [0]
        enqueue_mic_block(q, np.ones(4, dtype=np.float32), drops)
        enqueue_mic_block(q, np.ones(4, dtype=np.float32), drops)
        self.assertEqual(drops[0], 1)
        self.assertEqual(q.qsize(), 1)

    def test_drops_durante_voz_anulan_silencio(self) -> None:
        silence, seen = apply_capture_drops(
            speech_active=True, drop_hits=3, drops_seen=1, silence_seconds=0.7
        )
        self.assertEqual(silence, 0.0)
        self.assertEqual(seen, 3)

    def test_drops_sin_voz_no_tocan_silencio(self) -> None:
        silence, seen = apply_capture_drops(
            speech_active=False, drop_hits=2, drops_seen=0, silence_seconds=0.4
        )
        self.assertEqual(silence, 0.4)
        self.assertEqual(seen, 2)

    def test_prefijo_vad_energy_en_pi(self) -> None:
        self.assertEqual(vad_log_label("energy"), "energy-vad")
        self.assertEqual(vad_log_label("silero"), "silero-vad")

    def test_corte_loguea_duracion_del_array(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn("len(segment_audio) / 16000.0", src)
        self.assertIn("bloques descartados", src)


class TestDocsArecord(unittest.TestCase):
    def test_agents_menciona_arecord(self) -> None:
        text = Path(__file__).resolve().parent.joinpath("Agents.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("arecord", text)
        self.assertIn("hw:CARD=", text)
        self.assertIn("ALSA_CAPTURE_DEVICE", text)

    def test_latencia_documenta_pipewire_y_no_sudo(self) -> None:
        text = Path(__file__).resolve().parent.joinpath(
            "docs", "LATENCIA_AUDIO_CAMARA.md"
        ).read_text(encoding="utf-8")
        self.assertIn("arecord", text)
        self.assertIn("lsof", text)
        self.assertIn("pipewire", text.lower())
        self.assertIn("grupo audio", text.lower())
        self.assertNotIn("dwc_otg", text)
        self.assertNotIn("PA_ALSA_PLUGHW", text)


if __name__ == "__main__":
    unittest.main()
