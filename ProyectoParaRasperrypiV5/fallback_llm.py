"""fallback_llm.py — LLM local de fallback para intents no reconocidos.

Cuando el IntentDispatcher retorna ``unknown``, este módulo genera una
respuesta usando un GGUF local vía ``llama-cpp-python``.

Por defecto: Llama 3.2 3B Instruct Q4_K_M.
Opcional: ``LLM_PROFILE=1b`` (prueba descartada: calidad muy baja) o ``LLM_PROFILE=8b``.

El modelo se descarga la primera vez a ``~/.edge_ai_models/llm/``.
Override fino: ``LLM_HF_REPO`` + ``LLM_GGUF``.
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from debug_logger import get_debug_logger

# ---------------------------------------------------------------------------
# Modelo y descarga
# ---------------------------------------------------------------------------

_LLM_PROFILES: dict[str, tuple[str, str]] = {
    "1b": (
        "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
    ),
    "3b": (
        "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    ),
    "8b": (
        "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    ),
}

_CACHE_DIR = Path.home() / ".edge_ai_models" / "llm"


def selected_llm_spec() -> tuple[str, str]:
    """Repo HF y archivo GGUF según LLM_PROFILE o override explícito."""
    repo_ov = (os.environ.get("LLM_HF_REPO") or "").strip()
    file_ov = (os.environ.get("LLM_GGUF") or "").strip()
    if repo_ov and file_ov:
        return repo_ov, file_ov
    profile = (os.environ.get("LLM_PROFILE") or "3b").strip().lower()
    return _LLM_PROFILES.get(profile, _LLM_PROFILES["3b"])


def llm_n_ctx() -> int:
    """Default 2048. Rollback: LLM_N_CTX=1024 (el prompt largo no entra)."""
    try:
        return max(512, int(os.environ.get("LLM_N_CTX") or "2048"))
    except ValueError:
        return 2048


def llm_n_threads() -> int:
    """Default 4, como cuando respondía en ~30 s. Override: LLM_THREADS."""
    raw = (os.environ.get("LLM_THREADS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return 4
    return 4


def llm_generate_timeout_s() -> float:
    """Espera hasta 2 min a que Llama termine. Rollback: LLM_GENERATE_TIMEOUT=60."""
    try:
        return max(0.1, float(os.environ.get("LLM_GENERATE_TIMEOUT") or "120"))
    except ValueError:
        return 120.0

# ---------------------------------------------------------------------------
# System prompt — personalidad empática en español argentino (3 a 7 años)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Tu nombre es TEO. Sos un peluche que habla con nenes de 3 a 7 años. "
    "Primera persona; vos, mirá, dale. Nunca tercera persona ni 'el nene', 'el usuario' o 'el LLM'. "
    "Si preguntan cómo te llamás: Me llamo TEO. Máximo 25 palabras. "
    "Si no se entiende, pedí que repita. No inventes países ni datos. Si no sabés, decí no sé. "
    "Cuentas simples: da el resultado. Sin emojis, comillas ni asteriscos. "
    "NO ofrezcas cuentos ni historias. NO juegues veo veo ni Piedra Papel o Tijera: hay skill. "
    "Si pide un juego, ofrecé SOLO veo veo o piedra papel o tijera. "
    "Tags AL FINAL, nunca se dicen. No inventes tags. "
    "[INTENTS_OFF] si preguntás y esperás respuesta. "
    "[INTENTS_ON] obligatorio cuando dejás de preguntar. "
    "Si pide a mamá/papá: [NOTIFY_PARENT:razón explicandole al padre] y [INTENTS_ON]. "
    "[PLAY_MUSIC] solo si pide canción, música o bailar. [STOP_MUSIC] para parar. "
    "[NOTIFY_PARENT:razón explicandole al padre] SOLO si pide a mamá/papá, miedo, crisis o duele de verdad. "
    "NO uses [NOTIFY_PARENT] por una palabra suelta, un color, un juego, una verdura, un bicho o charla de jardín. "
    "[EXPRESSION:feliz|triste|sorprendido|enojado|neutral] "
    "[CELEBRATE:qué hizo] breve, no vacío. "
    "[CALM_MODE] si tiene sueño, está cansado o si el nene se despide.\n"
)

_CHILD_ASKED_STORY = re.compile(
    r"(cont(a|ame)|lee(me)?|narra(me)?).{0,24}(cuento|historia)"
    r"|\b(un|el)\s+cuento\b"
    r"|\bcuentos\b",
    re.IGNORECASE,
)
_STORY_OFFER = re.compile(
    r"(?i)("
    r"pedime\s+(un|una)?\s*(cuento|historia)"
    r"|historia\s+corta"
    r"|te\s+(cuento|narro|leo)\b"
    r"|quer[eé]s\s+(que\s+)?(te\s+)?cuente"
    r"|vamos\s+a\s+(leer|contar)\s"
    r"|te\s+cuento\s+una"
    r"|\bun\s+cuento\b"
    r"|\buna\s+historia\b"
    r")"
)
_NEUTRAL_AFTER_STRIP = "¡Qué bueno! Contame más."


def drop_unsolicited_story_offer(user_text: str, reply: str) -> str:
    """Saca invitaciones a cuento/historia si el nene no pidió una.

    Llama-3.2-3B copia la plantilla del system prompt y ofrece un cuento
    aunque el nene hable de otra cosa (p. ej. un sándwich).
    """
    if not (reply or "").strip():
        return reply
    user = user_text or ""
    if _CHILD_ASKED_STORY.search(user) or "leímos" in user.lower():
        return reply
    parts = re.split(r"(?<=[.!?])\s+", reply.strip())
    kept = [part for part in parts if part and not _STORY_OFFER.search(part)]
    cleaned = " ".join(kept).strip()
    return cleaned or _NEUTRAL_AFTER_STRIP


class FallbackLLM:
    """LLM local ligero para generar respuestas empáticas de fallback.

    Ciclo de vida:
        1. ``__init__()`` — solo prepara la configuración (sin carga pesada).
        2. ``load()`` — descarga (si es necesario) y carga el modelo en RAM.
           Debe llamarse en el hilo de AudioWorker durante el startup.
        3. ``generate(text, emotion)`` — genera una respuesta corta.
    """

    def __init__(self) -> None:
        self._llm: Any = None
        self._loaded = False
        self._history: list[dict[str, str]] = []
        self._gen_lock = threading.Lock()
        self.last_fail = ""

    def clear_history(self) -> None:
        """Borra el historial de conversación actual."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Carga del modelo (eager, llamada explícita durante startup)
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carga el GGUF una sola vez en este proceso y lo deja en RAM."""
        if self._loaded:
            return
        self._load_llama()

    def _load_llama(self) -> None:
        _dlog = get_debug_logger()

        try:
            from llama_cpp import Llama
        except ImportError:
            if _dlog:
                _dlog.log_output(
                    "LLM_INIT",
                    "llama-cpp-python no instalado — fallback LLM deshabilitado",
                )
            return

        _repo, filename = selected_llm_spec()
        model_path = self._ensure_model()
        n_threads = llm_n_threads()
        if _dlog:
            _dlog.log_input(
                "LLM_INIT",
                f"Cargando {filename} n_ctx={llm_n_ctx()} "
                f"threads={n_threads} timeout={llm_generate_timeout_s():.0f}s...",
            )

        _t0 = time.monotonic()
        n_batch = 64 if filename.startswith("Meta-Llama-3.1-8B") else 128
        try:
            os.environ["OMP_NUM_THREADS"] = str(n_threads)
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=llm_n_ctx(),
                n_threads=max(1, n_threads),
                n_batch=n_batch,
                n_gpu_layers=0,
                verbose=False,
            )
            self._loaded = True
            if _dlog:
                _dlog.log_output(
                    "LLM_INIT",
                    "Modelo cargado OK",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
        except Exception as exc:
            if _dlog:
                _dlog.log_output(
                    "LLM_INIT",
                    f"ERROR al cargar: {exc}. Rollback: LLM_PROFILE=8b",
                )

    @property
    def is_available(self) -> bool:
        """True si el modelo está cargado y listo para generar."""
        return self._loaded and self._llm is not None

    # ------------------------------------------------------------------
    # Generación de respuesta
    # ------------------------------------------------------------------

    def generate(
        self,
        text: str,
        emotion: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Genera una respuesta empática para el texto dado.

        Args:
            text: Texto transcripto del niño (ya sanitizado).
            emotion: Contexto emocional ``{"label": ..., "score": ...}``
                     o None si no hay emoción detectada.

        Returns:
            Texto de respuesta o cadena vacía si no se pudo generar.
        """
        self.last_fail = ""
        if not self.is_available:
            self.last_fail = "no disponible"
            return ""

        _dlog = get_debug_logger()
        if not self._gen_lock.acquire(blocking=False):
            self.last_fail = "ocupado"
            if _dlog:
                _dlog.log_output("LLM_GENERATE", "ocupado — no lanzo otra inferencia")
            return ""

        if _dlog:
            _dlog.log_input("LLM_GENERATE", f"text=\"{text}\"")

        _t0 = time.monotonic()
        timeout_s = llm_generate_timeout_s()
        box: list[Any] = []
        err: list[BaseException] = []

        def _run() -> None:
            try:
                box.append(self.complete_sync(text, emotion, history))
            except BaseException as exc:
                err.append(exc)
            finally:
                self._gen_lock.release()

        # AudioWorker espera hasta 2 min. El decode corre en LLMGenerate
        # para poder cortar la espera si OpenMP se cuelga.
        worker = threading.Thread(target=_run, name="LLMGenerate", daemon=True)
        try:
            worker.start()
        except Exception:
            self._gen_lock.release()
            return ""
        worker.join(timeout_s)
        if worker.is_alive():
            self.last_fail = "timeout"
            if _dlog:
                _dlog.log_output(
                    "LLM_GENERATE",
                    f"TIMEOUT {timeout_s:.0f}s — uso respuesta enlatada",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return ""

        if err:
            self.last_fail = str(err[0])
            if _dlog:
                _dlog.log_output(
                    "LLM_GENERATE",
                    f"ERROR: {err[0]}",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return ""

        response_text = str(box[0] if box else "")
        if _dlog:
            _dlog.log_output(
                "LLM_GENERATE",
                f"response=\"{response_text}\"",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )
        return response_text

    def complete_sync(
        self,
        text: str,
        emotion: dict[str, Any] | None,
        history: list[dict[str, str]] | None,
    ) -> str:
        """Inferencia bloqueante. El GGUF se queda en RAM entre turnos."""
        if self._llm is None:
            return ""
        messages = self._build_messages(
            text, emotion, history if history is not None else self._history
        )
        result = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=80,
            temperature=0.70,
            top_p=0.9,
            top_k=40,
            repeat_penalty=1.15,
            stop=[
                "<|eot_id|>",
                "<|start_header_id|>",
                "<|end_header_id|>",
                "<|im_end|>",
                "<|endoftext|>",
                "<|im_start|>",
            ],
        )
        raw_text = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return drop_unsolicited_story_offer(text, self._clean_response(raw_text))

    # ------------------------------------------------------------------
    # Limpieza y post-procesamiento de la respuesta
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_response(text: str) -> str:
        """Limpia emojis, acciones entre asteriscos y asegura máximo 25 palabras."""
        if not text:
            return ""

        # Eliminar acciones de roleplay como *sonríe* o (se ríe)
        cleaned = re.sub(r"\*[^*]*\*", "", text)
        cleaned = re.sub(r"\([^\)]*\)", "", cleaned)

        # Eliminar emojis y caracteres gráficos no verbalizables
        cleaned = re.sub(
            r"[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2b50]",
            "",
            cleaned,
        )

        # Limpiar comillas innecesarias y saltos de línea
        cleaned = cleaned.replace('"', "").replace("“", "").replace("”", "")
        cleaned = " ".join(cleaned.split()).strip()

        if not cleaned:
            cleaned = text.replace('"', "").strip()

        # Limitar estrictamente a un máximo de 25 palabras completas
        words = cleaned.split()
        if len(words) > 25:
            truncated = " ".join(words[:25])
            last_punct = max(
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
            )
            if last_punct > 15:
                cleaned = truncated[: last_punct + 1].strip()
            else:
                cleaned = truncated.rstrip(" ,;:-") + "."

        return cleaned

    # ------------------------------------------------------------------
    # Construcción del prompt de usuario
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(text: str, emotion: dict[str, Any] | None, history: list[dict[str, str]]) -> list[dict[str, str]]:
        """Arma los mensajes para el LLM con el sistema actualizado y el historial."""
        system_content = _SYSTEM_PROMPT
        
        if emotion:
            label = str(emotion.get("label", "")).lower()
            score = float(emotion.get("score", 0.0))
            if label == "triste" and score >= 0.35:
                system_content += "\nContexto: El nene parece estar triste. Respondé con mucha contención y dulzura."
            elif label == "enojado" and score >= 0.40:
                system_content += "\nContexto: El nene parece estar frustrado o enojado. Respondé con calma y paciencia."
            elif label == "feliz" and score >= 0.30:
                system_content += "\nContexto: El nene está contento. Respondé con entusiasmo y alegría."
            elif label == "sorprendido":
                system_content += "\nContexto: El nene está sorprendido."

        messages = [{"role": "system", "content": system_content}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})
        
        return messages

    # ------------------------------------------------------------------
    # Descarga del modelo GGUF
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_model() -> Path:
        """Retorna la ruta al modelo GGUF, descargándolo si es necesario."""
        repo, filename = selected_llm_spec()
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        model_path = _CACHE_DIR / filename

        if model_path.exists() and model_path.stat().st_size > 100_000_000:
            return model_path

        _dlog = get_debug_logger()
        if _dlog:
            _dlog.log_input(
                "LLM_DOWNLOAD",
                f"Descargando {filename} (solo primera vez)...",
            )

        _t0 = time.monotonic()
        model_url = f"https://huggingface.co/{repo}/resolve/main/{filename}"

        # Intentar descargar usando huggingface_hub si está disponible (maneja redirects y LFS)
        try:
            from huggingface_hub import hf_hub_download

            downloaded = hf_hub_download(
                repo_id=repo,
                filename=filename,
                local_dir=_CACHE_DIR,
            )
            return Path(downloaded)
        except Exception:
            # Fallback con urllib incluyendo User-Agent para evitar HTTP 401 de HF
            req = urllib.request.Request(
                model_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EdgeAI/1.0"},
            )
            with urllib.request.urlopen(req) as resp, open(model_path, "wb") as out_file:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out_file.write(chunk)

        if _dlog:
            size_mb = model_path.stat().st_size / (1024 * 1024)
            _dlog.log_output(
                "LLM_DOWNLOAD",
                f"Descarga completa ({size_mb:.0f} MB)",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )

        return model_path
