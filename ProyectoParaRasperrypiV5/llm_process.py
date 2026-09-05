"""Llama en un proceso hijo.

En la Pi, create_chat_completion en el mismo proceso que AudioWorker
se queda colgado: a los 15 s hay timeout, el lock queda tomado y todos
los unknown salen enlatados. El hijo se puede matar y volver a cargar.
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import time
from typing import Any, Callable

LogFn = Callable[[str], None]


class LlmRemote:
    def __init__(self, process: Any, req: Any, res: Any) -> None:
        self._process = process
        self._req = req
        self._res = res
        self.last_fail = ""

    @property
    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and bool(proc.is_alive())

    def ask(
        self,
        text: str,
        emotion: dict[str, Any] | None,
        history: list[dict[str, str]],
        timeout_s: float,
    ) -> str:
        self.last_fail = ""
        if not self.is_alive:
            self.last_fail = "hijo muerto"
            return ""
        self._req.put((text, emotion, history))
        try:
            status, payload = self._res.get(timeout=timeout_s)
        except queue.Empty:
            self.last_fail = "timeout"
            self.kill()
            return ""
        if status != "ok":
            self.last_fail = str(payload or "error")
            return ""
        return str(payload or "")

    def kill(self) -> None:
        proc = self._process
        if proc is None:
            return
        try:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1)
        except Exception:
            pass
        self._process = None


def _child_main(req: Any, res: Any) -> None:
    os.environ["LLM_IN_CHILD"] = "1"
    from fallback_llm import FallbackLLM, llm_n_threads

    n_threads = llm_n_threads()
    os.environ["OMP_NUM_THREADS"] = str(n_threads)
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    inner = FallbackLLM()
    try:
        inner.load()
    except Exception as exc:
        res.put(("error", str(exc)))
        return
    if not inner.is_available:
        res.put(("error", "llm no cargó"))
        return
    res.put(("ready", None))
    while True:
        job = req.get()
        if job is None:
            break
        text, emotion, history = job
        try:
            out = inner.complete_sync(text, emotion, history)
            res.put(("ok", out))
        except Exception as exc:
            res.put(("error", str(exc)))


def start_llm_process(
    log: LogFn | None = None,
    ready_timeout_s: float = 300.0,
) -> LlmRemote | None:
    from fallback_llm import llm_n_threads

    threads = llm_n_threads()
    if log:
        log(f"LLM hijo: threads={threads}")
    ctx = multiprocessing.get_context("spawn")
    req: Any = ctx.Queue()
    res: Any = ctx.Queue()
    proc = ctx.Process(target=_child_main, args=(req, res), name="LlmChild", daemon=True)
    proc.start()
    deadline = time.monotonic() + ready_timeout_s
    while time.monotonic() < deadline:
        if not proc.is_alive():
            if proc.exitcode is None:
                time.sleep(0.05)
                continue
            if res.empty():
                if log:
                    log(f"LLM hijo murió al cargar (exit={proc.exitcode}).")
                return None
        try:
            status, detail = res.get(timeout=1.0)
        except queue.Empty:
            continue
        if status == "ready":
            if log:
                log("LLM hijo listo")
            return LlmRemote(proc, req, res)
        if log:
            log(f"LLM hijo error: {detail}")
        if proc.is_alive():
            proc.terminate()
        return None
    if log:
        log("LLM hijo timeout al cargar.")
    if proc.is_alive():
        proc.terminate()
    return None
