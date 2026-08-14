"""Debug Logger — Sistema de logging detallado para modo --debug.

Crea un archivo .txt en la carpeta ``logs/`` con timestamps precisos
y trazabilidad de input/output de cada funcionalidad para identificar
cuellos de botella de rendimiento.

Uso:
    from debug_logger import init_debug_logger, get_debug_logger

    # En main(), solo si --debug:
    init_debug_logger()

    # En cualquier módulo:
    logger = get_debug_logger()
    if logger:
        logger.log("mensaje genérico")
        logger.log_input("COMPONENT", "descripción del input")
        logger.log_output("COMPONENT", "descripción del output", elapsed_ms=123.4)
"""
from __future__ import annotations

import platform
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np


class DebugLogger:
    """Logger thread-safe que escribe a un archivo .txt con timestamps."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._audio_counter = 0
        self._audio_counter_lock = threading.Lock()
        app_dir = Path(__file__).resolve().parent
        self._log_dir = log_dir or (app_dir / "logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # Carpeta de audios de debug (hermana de logs/)
        self._audio_dir = app_dir / "audios"
        self._audio_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        filename = f"debug_{now.strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        self._log_path = self._log_dir / filename
        self._start_time = time.monotonic()

        # Write header
        with open(self._log_path, "w", encoding="utf-8") as f:
            f.write("=" * 48 + "\n")
            f.write("=== Edge AI Debug Log ===\n")
            f.write(f"Inicio: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(
                f"Plataforma: {platform.system()}-{platform.release()}, "
                f"Python {sys.version.split()[0]}\n"
            )
            f.write("=" * 48 + "\n\n")

    @property
    def log_path(self) -> Path:
        """Ruta absoluta del archivo de log actual."""
        return self._log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, message: str) -> None:
        """Escribe un mensaje genérico con timestamp."""
        self._write(message)

    def log_input(self, component: str, description: str) -> None:
        """Marca la entrada a una funcionalidad/etapa del pipeline.

        Ejemplo de salida::

            [13:14:30.100] >>> [TRANSCRIPTION] Audio segment (2.3s, 36800 samples)
        """
        self._write(f">>> [{component}] {description}")

    def log_output(
        self,
        component: str,
        description: str,
        elapsed_ms: float | None = None,
    ) -> None:
        """Marca la salida de una funcionalidad/etapa del pipeline.

        Ejemplo de salida::

            [13:14:31.234] <<< [TRANSCRIPTION] "hola quiero jugar" (1134ms)
        """
        suffix = f" ({elapsed_ms:.0f}ms)" if elapsed_ms is not None else ""
        self._write(f"<<< [{component}] {description}{suffix}")

    # ------------------------------------------------------------------
    # Audio debug — guardar WAV crudos y procesados junto a transcripción
    # ------------------------------------------------------------------

    def get_audio_debug_dir(self) -> Path:
        """Retorna la carpeta ``audios/`` creándola si no existe."""
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        return self._audio_dir

    def save_debug_audio(
        self,
        raw_audio: np.ndarray,
        processed_audio: np.ndarray,
        transcript_text: str,
        sample_rate: int = 16000,
    ) -> None:
        """Guarda archivos de debug de una transcripción.

        Genera tres archivos en ``audios/``:
          - ``{ts}_{counter}_crudo.wav``      — audio tal cual lo captura el mic
          - ``{ts}_{counter}_procesado.wav``   — audio post-pipeline (pre-Whisper)
          - ``{ts}_{counter}_transcripcion.txt`` — texto transcripto + métricas

        Nunca lanza excepciones para no afectar el pipeline principal.
        """
        try:
            now = datetime.now()
            ts_str = now.strftime("%Y-%m-%d_%H-%M-%S")

            with self._audio_counter_lock:
                self._audio_counter += 1
                counter = self._audio_counter

            base_name = f"{ts_str}_{counter:03d}"
            audio_dir = self.get_audio_debug_dir()

            # Guardar audio crudo
            raw_path = audio_dir / f"{base_name}_crudo.wav"
            self._save_wav(raw_path, raw_audio, sample_rate)

            # Guardar audio procesado (post-pipeline, pre-Whisper)
            proc_path = audio_dir / f"{base_name}_procesado.wav"
            self._save_wav(proc_path, processed_audio, sample_rate)

            # Calcular métricas
            raw_duration_s = len(raw_audio) / sample_rate
            proc_duration_s = len(processed_audio) / sample_rate
            raw_rms = float(np.sqrt(np.mean(raw_audio ** 2))) if len(raw_audio) > 0 else 0.0
            proc_rms = float(np.sqrt(np.mean(processed_audio ** 2))) if len(processed_audio) > 0 else 0.0

            # Guardar transcripción con métricas
            txt_path = audio_dir / f"{base_name}_transcripcion.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Audio crudo: {raw_duration_s:.2f}s ({len(raw_audio)} samples)\n")
                f.write(f"Audio procesado: {proc_duration_s:.2f}s ({len(processed_audio)} samples)\n")
                f.write(f"RMS crudo: {raw_rms:.6f}\n")
                f.write(f"RMS procesado: {proc_rms:.6f}\n")
                f.write(f"Transcripción: \"{transcript_text}\"\n")

            self._write(
                f"[AUDIO_DEBUG] Guardados: {base_name}_crudo.wav, "
                f"{base_name}_procesado.wav, {base_name}_transcripcion.txt"
            )
        except Exception as exc:
            # Nunca interrumpir el pipeline principal por un error de debug
            try:
                self._write(f"[AUDIO_DEBUG] Error guardando audios: {exc}")
            except Exception:
                pass

    @staticmethod
    def _save_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
        """Guarda audio float32 como WAV 16-bit PCM sin dependencias externas."""
        # Convertir float32 [-1.0, 1.0] a int16
        audio_clipped = np.clip(audio, -1.0, 1.0)
        audio_int16 = (audio_clipped * 32767).astype(np.int16)
        raw_data = audio_int16.tobytes()

        n_channels = 1
        sample_width = 2  # 16-bit = 2 bytes
        n_frames = len(audio_int16)
        data_size = n_frames * n_channels * sample_width

        with open(path, "wb") as f:
            # RIFF header
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + data_size))
            f.write(b"WAVE")
            # fmt chunk
            f.write(b"fmt ")
            f.write(struct.pack("<I", 16))  # chunk size
            f.write(struct.pack("<H", 1))   # PCM format
            f.write(struct.pack("<H", n_channels))
            f.write(struct.pack("<I", sample_rate))
            f.write(struct.pack("<I", sample_rate * n_channels * sample_width))  # byte rate
            f.write(struct.pack("<H", n_channels * sample_width))  # block align
            f.write(struct.pack("<H", sample_width * 8))  # bits per sample
            # data chunk
            f.write(b"data")
            f.write(struct.pack("<I", data_size))
            f.write(raw_data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _timestamp(self) -> str:
        """Genera un timestamp ``[HH:MM:SS.mmm]``."""
        now = datetime.now()
        return now.strftime("[%H:%M:%S.") + f"{now.microsecond // 1000:03d}]"

    def _write(self, message: str) -> None:
        ts = self._timestamp()
        line = f"{ts} {message}\n"
        with self._lock:
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass  # Never crash the app due to logging


# ═══════════════════════════════════════════════════════════════════════════
# Singleton global
# ═══════════════════════════════════════════════════════════════════════════

_global_logger: DebugLogger | None = None


def init_debug_logger(log_dir: Path | None = None) -> DebugLogger:
    """Inicializa el logger global.  Llamar solo una vez desde ``main()``."""
    global _global_logger
    _global_logger = DebugLogger(log_dir=log_dir)
    _global_logger.log(
        f"Modo debug activado, log: {_global_logger.log_path}"
    )
    return _global_logger


def get_debug_logger() -> DebugLogger | None:
    """Retorna el logger global o ``None`` si no fue inicializado."""
    return _global_logger
