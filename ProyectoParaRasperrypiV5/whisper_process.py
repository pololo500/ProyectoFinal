"""Whisper en un proceso hijo.

En Raspberry Pi 5, CTranslate2 con compute int8 en el mismo proceso que
OpenCV/Piper suele morir con Bus error y tumba toda la app. El hijo aísla
ese crash: Teo sigue con LCD, TTS y pulsador.
"""
from __future__ import annotations

import multiprocessing
import os
import platform
import queue
import time
from types import SimpleNamespace
from typing import Any, Callable


LogFn = Callable[[str], None]


def default_compute_type() -> str:
    override = (os.environ.get("WHISPER_COMPUTE") or "").strip()
    if override:
        return override
    return "int8"


def whisper_cpu_threads() -> int:
    try:
        return max(1, int(os.environ.get("WHISPER_THREADS") or "2"))
    except ValueError:
        return 2


def child_force_cpu_isa() -> str | None:
    """Solo si el usuario lo pide. GENERIC en ARM también puede SIGBUS."""
    override = (os.environ.get("CT2_FORCE_CPU_ISA") or "").strip()
    return override or None


def whisper_model_candidates(preferred: str) -> tuple[str, ...]:
    """Si el pedido muere al cargar, probar tamaños más chicos."""
    wanted = (preferred or "medium").strip() or "medium"
    rest = ("small", "tiny")
    out: list[str] = [wanted]
    for size in rest:
        if size not in out:
            out.append(size)
    return tuple(out)


def is_bus_exit(code: int | None) -> bool:
    """Python multiprocessing: -N = señal N. SIGBUS = 7."""
    if code is None:
        return False
    return code in (-7, 7, 135)


def stt_empty_log(*, whisper_available: bool, elapsed_ms: float) -> str:
    if not whisper_available:
        return "[STT] Sin Whisper — el audio se cortó pero no se transcribe"
    return f"[STT] Audio procesado ({elapsed_ms:.0f}ms) — no se detectó texto"


def kernel_page_size() -> int | None:
    try:
        return int(os.sysconf("SC_PAGESIZE"))
    except (AttributeError, ValueError, OSError):
        return None


def ctranslate2_compatible() -> bool:
    """CTranslate2 (faster-whisper) SIGBUS en Pi 5 con páginas de 16K."""
    size = kernel_page_size()
    if size is None:
        return True
    return size <= 4096


def page_size_hint() -> str | None:
    size = kernel_page_size()
    if size is None or size <= 4096:
        return None
    return (
        f"Kernel con páginas de {size} bytes. "
        "Si el hijo pega Bus error, cargo Whisper en este proceso."
    )


def load_faster_whisper(
    model_size: str,
    compute_type: str | None = None,
    cpu_threads: int | None = None,
    log: LogFn | None = None,
) -> Any:
    """Carga faster-whisper en este proceso (como el proyecto que sí transcribe)."""
    from faster_whisper import WhisperModel

    compute = compute_type or default_compute_type()
    threads = cpu_threads if cpu_threads is not None else whisper_cpu_threads()
    if log:
        log(
            f"Whisper en proceso: modelo={model_size} compute={compute} threads={threads}"
        )
    return WhisperModel(
        model_size,
        device="cpu",
        compute_type=compute,
        cpu_threads=threads,
        num_workers=1,
    )


def _child_main(
    req: Any,
    res: Any,
    model_size: str,
    compute_type: str,
    cpu_threads: int,
) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ["CTRANSLATE2_NUM_THREADS"] = str(cpu_threads)
    isa = child_force_cpu_isa()
    if isa:
        os.environ["CT2_FORCE_CPU_ISA"] = isa
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=1,
        )
        res.put(("ready", None))
    except Exception as exc:
        res.put(("error", str(exc)))
        return

    while True:
        job = req.get()
        if job is None:
            break
        audio, kwargs = job
        try:
            segments, _info = model.transcribe(audio, **kwargs)
            payload = []
            for segment in segments:
                payload.append(
                    {
                        "text": segment.text,
                        "avg_logprob": getattr(segment, "avg_logprob", None),
                        "no_speech_prob": getattr(segment, "no_speech_prob", None),
                    }
                )
            res.put(("ok", payload))
        except Exception as exc:
            res.put(("error", str(exc)))


class RemoteWhisper:
    def __init__(self, process: Any, req: Any, res: Any) -> None:
        self._process = process
        self._req = req
        self._res = res

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[list[Any], None]:
        if self._process is None or not self._process.is_alive():
            return [], None
        self._req.put((audio, kwargs))
        try:
            status, payload = self._res.get(timeout=60)
        except Exception:
            return [], None
        if status != "ok" or not payload:
            return [], None
        segments = [SimpleNamespace(**item) for item in payload]
        return segments, None

    def close(self) -> None:
        try:
            self._req.put(None)
        except Exception:
            pass
        proc = self._process
        if proc is not None and proc.is_alive():
            proc.join(timeout=2)
            if proc.is_alive():
                proc.terminate()


def start_whisper_process(
    model_size: str,
    compute_type: str | None = None,
    cpu_threads: int | None = None,
    log: LogFn | None = None,
    ready_timeout_s: float = 300.0,
) -> RemoteWhisper | None:
    compute = compute_type or default_compute_type()
    threads = cpu_threads if cpu_threads is not None else whisper_cpu_threads()
    if log:
        log(f"Whisper hijo: modelo={model_size} compute={compute} threads={threads}")
    ctx = multiprocessing.get_context("spawn")
    req: Any = ctx.Queue()
    res: Any = ctx.Queue()
    proc = ctx.Process(
        target=_child_main,
        args=(req, res, model_size, compute, threads),
        name="WhisperChild",
        daemon=True,
    )
    proc.start()
    deadline = time.monotonic() + ready_timeout_s
    while time.monotonic() < deadline:
        if not proc.is_alive():
            # spawn tarda: is_alive() puede ser False con exitcode None un instante.
            if proc.exitcode is None:
                time.sleep(0.05)
                continue
            if res.empty():
                code = proc.exitcode
                if log:
                    log(f"Whisper hijo murió al cargar (exit={code}). Sigo sin STT.")
                    if is_bus_exit(code):
                        hint = page_size_hint()
                        if hint:
                            log(hint)
                return None
        try:
            status, detail = res.get(timeout=1.0)
        except queue.Empty:
            continue
        if status == "ready":
            if log:
                log("Whisper hijo listo")
            return RemoteWhisper(proc, req, res)
        if log:
            log(f"Whisper hijo error: {detail}")
        if proc.is_alive():
            proc.terminate()
        return None
    if log:
        log("Whisper hijo timeout al cargar. Sigo sin STT.")
    if proc.is_alive():
        proc.terminate()
    return None
