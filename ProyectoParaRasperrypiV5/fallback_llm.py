"""fallback_llm.py — LLM local de fallback para intents no reconocidos.

Cuando el IntentDispatcher retorna ``unknown``, este módulo genera una
respuesta empática usando un LLM pequeño (internlm2.5-1.8B-chat Q4_K_M)
ejecutado localmente vía ``llama-cpp-python``.

El modelo se descarga automáticamente desde HuggingFace la primera vez
y se cachea en ``~/.edge_ai_models/llm/``.

Diseñado para Raspberry Pi 5 (ARM64, CPU-only, ~1.2 GB RAM).
"""
from __future__ import annotations

import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from debug_logger import get_debug_logger

# ---------------------------------------------------------------------------
# Modelo y descarga
# ---------------------------------------------------------------------------

_MODEL_REPO = "bartowski/Llama-3.2-3B-Instruct-GGUF"
_MODEL_FILENAME = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
_MODEL_URL = (
    f"https://huggingface.co/{_MODEL_REPO}/resolve/main/{_MODEL_FILENAME}"
)
_CACHE_DIR = Path.home() / ".edge_ai_models" / "llm"

# ---------------------------------------------------------------------------
# System prompt — personalidad empática en español argentino (3 a 7 años)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Tu nombre es TEO. Sos un robot de peluche mágico y cariñoso que habla con nenes de 3 a 7 años. "
    "Hablá siempre en primera persona y dirigite directamente al nene (usando 'vos', 'mirá', 'dale'). "
    "NUNCA hables del nene en tercera persona. NUNCA menciones 'el nene', 'el usuario' ni 'el LLM'. "
    "Si te preguntan cómo te llamás, respondé simplemente 'Me llamo TEO' y nada más.\n"
    "Tus respuestas deben ser MUY CORTAS (máximo 20 palabras, 1 o 2 oraciones breves). "
    "Si escuchás algo que no se entiende bien, seguile la corriente con alegría o hacele una pregunta sencilla. "
    "No uses emojis, ni comillas, ni asteriscos."
)


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

    def clear_history(self) -> None:
        """Borra el historial de conversación actual."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Carga del modelo (eager, llamada explícita durante startup)
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Descarga (si necesario) y carga el modelo GGUF en RAM.

        Diseñado para ser invocado una vez durante el startup del
        AudioWorker, secuencialmente después de Whisper y VAD.
        """
        if self._loaded:
            return

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

        model_path = self._ensure_model()
        if _dlog:
            _dlog.log_input("LLM_INIT", f"Cargando {_MODEL_FILENAME}...")

        _t0 = time.monotonic()
        try:
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=1024,         # Contexto cómodo para prompt + respuesta
                n_threads=4,        # 4 cores de CPU
                n_batch=128,        # Batch eficiente
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
                _dlog.log_output("LLM_INIT", f"ERROR al cargar: {exc}")

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
    ) -> str:
        """Genera una respuesta empática para el texto dado.

        Args:
            text: Texto transcripto del niño (ya sanitizado).
            emotion: Contexto emocional ``{"label": ..., "score": ...}``
                     o None si no hay emoción detectada.

        Returns:
            Texto de respuesta o cadena vacía si no se pudo generar.
        """
        if not self.is_available:
            return ""

        _dlog = get_debug_logger()
        messages = self._build_messages(text, emotion, self._history)

        if _dlog:
            _dlog.log_input("LLM_GENERATE", f"text=\"{text}\"")

        _t0 = time.monotonic()
        try:
            result = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=80,
                temperature=0.70,
                top_p=0.9,
                top_k=40,
                repeat_penalty=1.15,
                stop=["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
            )

            raw_text = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            response_text = self._clean_response(raw_text)

            # Guardar la interacción en el historial
            if response_text:
                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": response_text})
                # Mantener solo las últimas 4 interacciones (2 turnos) para no sobrepasar el contexto
                if len(self._history) > 4:
                    self._history = self._history[-4:]

            if _dlog:
                _dlog.log_output(
                    "LLM_GENERATE",
                    f"response=\"{response_text}\"",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return response_text

        except Exception as exc:
            if _dlog:
                _dlog.log_output(
                    "LLM_GENERATE",
                    f"ERROR: {exc}",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return ""

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
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        model_path = _CACHE_DIR / _MODEL_FILENAME

        if model_path.exists() and model_path.stat().st_size > 100_000_000:
            return model_path

        _dlog = get_debug_logger()
        if _dlog:
            _dlog.log_input(
                "LLM_DOWNLOAD",
                f"Descargando {_MODEL_FILENAME} (solo primera vez)...",
            )

        _t0 = time.monotonic()

        # Intentar descargar usando huggingface_hub si está disponible (maneja redirects y LFS)
        try:
            from huggingface_hub import hf_hub_download

            downloaded = hf_hub_download(
                repo_id=_MODEL_REPO,
                filename=_MODEL_FILENAME,
                local_dir=_CACHE_DIR,
            )
            return Path(downloaded)
        except Exception:
            # Fallback con urllib incluyendo User-Agent para evitar HTTP 401 de HF
            req = urllib.request.Request(
                _MODEL_URL,
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
