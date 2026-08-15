"""cloud_services.py — Servicios cloud gratuitos para STT, LLM y TTS.

Provee alternativas cloud al procesamiento local cuando el usuario
selecciona el modo "Nube" en la UI. Todas las APIs son 100% gratuitas:

- STT: Groq Whisper API (whisper-large-v3-turbo)
- LLM: Groq Chat Completions (llama-3.3-70b-versatile)
- TTS: edge-tts (Microsoft Neural Voices, sin API key)

Diseñado para Raspberry Pi 5 (4GB RAM): estos servicios liberan ~3GB
de RAM al no cargar Whisper, spaCy, LLM local ni Piper.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import struct
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from debug_logger import get_debug_logger


# ═══════════════════════════════════════════════════════════════════════════
# Cloud STT — Groq Whisper API (con normalización y fallback a Google Speech)
# ═══════════════════════════════════════════════════════════════════════════

class CloudSTT:
    """Transcripción de audio de alta precisión vía Groq Whisper + Google Speech.

    Aplica preprocesamiento acústico antes de enviar:
    - Eliminación de componente DC (offset)
    - Filtro de energía RMS para descartar ruidos eléctricos
    - Normalización de volumen adaptativa (lleva el pico a 0.9) para amplificar voces bajas
    - Padding mínimo para que Whisper reciba contexto suficiente
    - Fallback a Google Speech Recognition si Groq falla o no devuelve texto
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: Any = None

    def _ensure_client(self) -> Any:
        """Inicializa el cliente Groq de forma lazy."""
        if self._client is None and self._api_key:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
        return self._client

    @staticmethod
    def _prepare_audio(audio: np.ndarray, sample_rate: int = 16000) -> bytes | None:
        """Preprocesa el audio para ASR: elimina DC, normaliza volumen y genera WAV bytes."""
        if audio.size == 0:
            return None

        # 1. Eliminar offset DC
        audio = audio - np.mean(audio)

        # 2. Filtro de silencio / ruido eléctrico
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.003:
            return None

        # 3. Normalizar volumen (llevar el pico a 0.9 para máxima claridad)
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-5:
            audio = audio * (0.9 / peak)

        # 4. Asegurar duración mínima de 1.0s con padding simétrico
        min_samples = int(sample_rate * 1.0)
        if len(audio) < min_samples:
            pad = min_samples - len(audio)
            pad_before = pad // 2
            pad_after = pad - pad_before
            audio = np.pad(audio, (pad_before, pad_after), mode="constant")

        # 5. Convertir a PCM 16-bit
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()

    def transcribe(self, audio_segment: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe un segmento de audio usando Groq Whisper (y fallback a Google).

        Args:
            audio_segment: Audio float32, mono.
            sample_rate: Frecuencia de muestreo (default 16000).

        Returns:
            Texto transcrito, o cadena vacía si no se detectó habla.
        """
        _dlog = get_debug_logger()
        _t0 = time.monotonic()

        wav_bytes = self._prepare_audio(audio_segment, sample_rate)
        if wav_bytes is None:
            return ""

        text = ""

        # 1. Intentar con Groq Whisper Large v3 Turbo (ultra rápido ~200ms)
        try:
            client = self._ensure_client()
            if client is not None:
                if _dlog:
                    _dlog.log_input("CLOUD_STT", f"Enviando {len(wav_bytes)} bytes a Groq Whisper")

                transcription = client.audio.transcriptions.create(
                    file=("audio.wav", wav_bytes),
                    model="whisper-large-v3-turbo",
                    language="es",
                    temperature=0.0,
                    response_format="json",
                )
                text = transcription.text.strip() if transcription.text else ""
        except Exception as exc:
            if _dlog:
                _dlog.log_output("CLOUD_STT", f"Groq Whisper error: {exc}")
            print(f"[CloudSTT] Groq Whisper error: {exc}", flush=True)

        # 2. Fallback a Google Speech Recognition si Groq no devolvió texto
        if not text:
            try:
                import speech_recognition as sr

                recognizer = sr.Recognizer()
                with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                    audio_data = recognizer.record(source)
                google_text = recognizer.recognize_google(audio_data, language="es-AR")
                if google_text:
                    text = google_text.strip()
                    if _dlog:
                        _dlog.log_output("CLOUD_STT", f"Recuperado vía Google Speech: '{text}'")
            except Exception:
                pass

        if _dlog:
            _dlog.log_output(
                "CLOUD_STT",
                f'"{text}"' if text else "sin transcripción",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )

        return text


# ═══════════════════════════════════════════════════════════════════════════
# Cloud LLM — Groq Chat Completions
# ═══════════════════════════════════════════════════════════════════════════

class CloudLLM:
    """LLM empático vía Groq Chat Completions (gratuito).

    Genera respuestas empáticas en español argentino para intents
    no reconocidos. Usa el mismo system prompt de TEO.
    """

    _SYSTEM_PROMPT = (
        "Tu nombre es TEO. Sos un robot de peluche mágico y cariñoso que habla con nenes de 3 a 7 años. "
        "Hablá siempre en primera persona y dirigite directamente al nene (usando 'vos', 'mirá', 'dale'). "
        "NUNCA hables del nene en tercera persona. NUNCA menciones 'el nene', 'el usuario' ni 'el LLM'. "
        "Si te preguntan cómo te llamás, respondé simplemente 'Me llamo TEO' y nada más.\n"
        "Tus respuestas deben ser MUY CORTAS (máximo 20 palabras, 1 o 2 oraciones breves). "
        "Si escuchás algo que no se entiende bien, seguile la corriente con alegría o hacele una pregunta sencilla. "
        "No uses emojis, ni comillas, ni asteriscos."
    )

    _MODEL = "llama-3.3-70b-versatile"
    _MAX_HISTORY = 4  # Últimos 4 turnos de contexto

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: Any = None
        self._history: list[dict[str, str]] = []

    @property
    def is_available(self) -> bool:
        """Siempre disponible si hay API key."""
        return bool(self._api_key)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
        return self._client

    def clear_history(self) -> None:
        """Borra el historial de conversación."""
        self._history.clear()

    def generate(self, user_text: str, emotion: dict | None = None) -> str:
        """Genera una respuesta empática para el texto del usuario.

        Args:
            user_text: Lo que dijo el nene (transcripción).
            emotion: Emoción detectada (dict con 'label' y 'score'), o None.

        Returns:
            Respuesta de TEO, o cadena vacía si hay error.
        """
        _dlog = get_debug_logger()
        _t0 = time.monotonic()

        try:
            client = self._ensure_client()

            # Construir contexto emocional
            emotion_hint = ""
            if emotion and emotion.get("label") and emotion["label"] != "neutral":
                emotion_hint = f" (El nene parece estar {emotion['label']})"

            # Agregar mensaje del usuario al historial
            self._history.append({
                "role": "user",
                "content": user_text + emotion_hint,
            })

            # Recortar historial
            if len(self._history) > self._MAX_HISTORY * 2:
                self._history = self._history[-self._MAX_HISTORY * 2:]

            messages = [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                *self._history,
            ]

            if _dlog:
                _dlog.log_input("CLOUD_LLM", f'text="{user_text}", emotion={emotion}')

            response = client.chat.completions.create(
                model=self._MODEL,
                messages=messages,
                max_tokens=80,
                temperature=0.7,
            )

            reply = response.choices[0].message.content.strip() if response.choices else ""

            # Agregar respuesta al historial
            if reply:
                self._history.append({
                    "role": "assistant",
                    "content": reply,
                })

            if _dlog:
                _dlog.log_output(
                    "CLOUD_LLM",
                    f'"{reply}"',
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )

            return reply

        except Exception as exc:
            if _dlog:
                _dlog.log_output("CLOUD_LLM", f"ERROR: {exc}")
            print(f"[CloudLLM] Error: {exc}", flush=True)
            return ""


# ═══════════════════════════════════════════════════════════════════════════
# Cloud TTS — gTTS (Google Text-to-Speech con acento cálido y caché LRU)
# ═══════════════════════════════════════════════════════════════════════════

class CloudTTS:
    """TTS gratuito vía gTTS (Google Text-to-Speech).

    Usa la voz en español con tld='com.mx' para un tono dulce, pausado y cálido,
    ideal para un peluche interactivo de apego (probado en el PoC original).

    Incluye un sistema de caché en disco con límite de tamaño (LRU):
    - Las frases repetidas se reproducen a 0ms de latencia (sin usar internet).
    - Límite máximo configurable (default: 50 MB) para proteger la tarjeta SD de la Pi.
    - Si se excede el límite, se purgan automáticamente los audios menos usados.
    """

    _LANG = "es"
    _TLD = "com.mx"
    _MAX_CACHE_BYTES = 50 * 1024 * 1024  # 50 MB

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        if cache_dir is None:
            self._cache_dir = Path.home() / ".edge_ai_models" / "cache_voces"
        else:
            self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, text: str) -> Path:
        """Genera un path único por hash MD5 del texto normalizado."""
        norm_text = text.strip().lower()
        key = f"{norm_text}_{self._LANG}_{self._TLD}"
        name_hash = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{name_hash}.mp3"

    def _enforce_cache_limit(self) -> None:
        """Purga los archivos más viejos (LRU por mtime) si se supera el límite de 50MB."""
        try:
            mp3_files = list(self._cache_dir.glob("*.mp3"))
            total_size = sum(f.stat().st_size for f in mp3_files)

            if total_size <= self._MAX_CACHE_BYTES:
                return

            # Ordenar por fecha de última modificación (los más viejos primero)
            mp3_files.sort(key=lambda f: f.stat().st_mtime)

            for f in mp3_files:
                if total_size <= int(self._MAX_CACHE_BYTES * 0.8):  # Liberar hasta el 80%
                    break
                file_size = f.stat().st_size
                try:
                    f.unlink()
                    total_size -= file_size
                except Exception:
                    pass
        except Exception:
            pass

    def synthesize_to_audio(self, text: str) -> tuple[np.ndarray, int] | None:
        """Sintetiza texto a audio usando gTTS + caché local."""
        _dlog = get_debug_logger()
        _t0 = time.monotonic()
        clean_text = (text or "").strip()
        if not clean_text:
            return None

        cache_path = self._get_cache_path(clean_text)
        from_cache = False

        try:
            # 1. Si está en caché, leer directamente del archivo (0ms de red)
            if cache_path.exists() and cache_path.stat().st_size > 0:
                from_cache = True
                with open(cache_path, "rb") as f:
                    mp3_data = f.read()
                # Actualizar mtime para la política LRU
                try:
                    cache_path.touch(exist_ok=True)
                except Exception:
                    pass
            else:
                # 2. Si no está en caché, descargar con gTTS
                import gtts

                tts = gtts.gTTS(text=clean_text, lang=self._LANG, tld=self._TLD, slow=False)
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                mp3_data = buf.getvalue()

                # Guardar en caché y verificar límite de espacio
                try:
                    with open(cache_path, "wb") as f:
                        f.write(mp3_data)
                    self._enforce_cache_limit()
                except Exception:
                    pass

            # 3. Decodificar MP3 a float32 array en memoria
            audio_array, sample_rate = self._decode_mp3(mp3_data)
            if audio_array is None:
                return None

            if _dlog:
                origin = "CACHE_LOCAL (0ms red)" if from_cache else "GOOGLE_GTTS"
                _dlog.log_output(
                    "CLOUD_TTS",
                    f"[{origin}] Sintetizado ({len(audio_array)} samples, {sample_rate}Hz)",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )

            return audio_array, sample_rate

        except Exception as exc:
            if _dlog:
                _dlog.log_output("CLOUD_TTS", f"ERROR: {exc}")
            print(f"[CloudTTS] Error con gTTS: {exc}", flush=True)
            return None

    @staticmethod
    def _decode_mp3(mp3_data: bytes) -> tuple[np.ndarray | None, int]:
        """Decodifica MP3 a float32 ndarray usando soundfile (en memoria)."""
        # 1. soundfile (soporta MP3 nativamente en memoria vía libsndfile)
        try:
            import soundfile as sf

            buf = io.BytesIO(mp3_data)
            audio_array, sample_rate = sf.read(buf, dtype="float32")
            if audio_array.ndim > 1:
                audio_array = audio_array[:, 0]  # Mono
            return audio_array, sample_rate
        except Exception:
            pass

        # 2. Fallback: minimp3
        try:
            import minimp3

            decoder = minimp3.Decoder()
            frames = decoder.decode(mp3_data)
            audio_int16 = np.frombuffer(frames[0], dtype=np.int16)
            sample_rate = frames[1]
            audio_float = audio_int16.astype(np.float32) / 32768.0
            return audio_float, sample_rate
        except ImportError:
            pass

        # 3. Fallback: pydub
        try:
            from pydub import AudioSegment

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(mp3_data)
                tmp_path = tmp.name

            try:
                audio_seg = AudioSegment.from_mp3(tmp_path)
                audio_seg = audio_seg.set_channels(1)
                samples = np.array(audio_seg.get_array_of_samples(), dtype=np.float32)
                samples /= 32768.0
                return samples, audio_seg.frame_rate
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

        # 4. Fallback: subprocess con ffmpeg directo
        try:
            import subprocess

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_in:
                tmp_in.write(mp3_data)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path.replace(".mp3", ".wav")

            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in_path,
                     "-ac", "1", "-ar", "24000",
                     "-f", "wav", tmp_out_path],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                with wave.open(tmp_out_path, "rb") as wf:
                    sr = wf.getframerate()
                    raw = wf.readframes(wf.getnframes())
                    audio_int16 = np.frombuffer(raw, dtype=np.int16)
                    return audio_int16.astype(np.float32) / 32768.0, sr
            finally:
                Path(tmp_in_path).unlink(missing_ok=True)
                Path(tmp_out_path).unlink(missing_ok=True)
        except Exception:
            pass

        print("[CloudTTS] No se pudo decodificar MP3 (instalar soundfile)", flush=True)
        return None, 0
