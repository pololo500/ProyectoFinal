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
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


class DebugLogger:
    """Logger thread-safe que escribe a un archivo .txt con timestamps."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        app_dir = Path(__file__).resolve().parent
        self._log_dir = log_dir or (app_dir / "logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)

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
