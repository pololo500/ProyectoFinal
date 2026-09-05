#!/usr/bin/env python3
"""Sonda aislada de CTranslate2/faster-whisper (sin app.py)."""
from __future__ import annotations

import os
import sys


def main() -> None:
    try:
        page = int(os.sysconf("SC_PAGESIZE"))
    except (AttributeError, ValueError, OSError):
        page = None
    print(f"PAGE_SIZE={page}", flush=True)
    try:
        import ctranslate2

        print(f"ctranslate2={ctranslate2.__version__}", flush=True)
        print("compute=", ctranslate2.get_supported_compute_types("cpu"), flush=True)
    except Exception as exc:
        print(f"import ctranslate2 FALLÓ: {exc}", flush=True)
        sys.exit(2)
    try:
        from faster_whisper import WhisperModel

        print("cargando tiny int8...", flush=True)
        WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1)
        print("OK tiny int8", flush=True)
    except Exception as exc:
        print(f"WhisperModel FALLÓ: {exc}", flush=True)
        sys.exit(3)
    print("CTranslate2 funciona en este proceso.", flush=True)


if __name__ == "__main__":
    main()
