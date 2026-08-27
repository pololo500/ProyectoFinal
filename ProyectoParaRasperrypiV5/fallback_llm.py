"""fallback_llm.py — LLM local de fallback para intents no reconocidos.

Cuando el IntentDispatcher retorna ``unknown``, este módulo genera una
respuesta usando un GGUF local vía ``llama-cpp-python``.

Por defecto: Llama 3.1 8B Instruct Q4_K_M (RAM justa junto a Whisper medium).
Rollback al 3B de hoy: ``LLM_PROFILE=3b``.

El modelo se descarga la primera vez a ``~/.edge_ai_models/llm/``.
Override fino: ``LLM_HF_REPO`` + ``LLM_GGUF``.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from debug_logger import get_debug_logger

# ---------------------------------------------------------------------------
# Modelo y descarga
# ---------------------------------------------------------------------------

_LLM_PROFILES: dict[str, tuple[str, str]] = {
    # Rollback: lo que corre hoy (Llama 3.2 3B + Whisper medium).
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
    profile = (os.environ.get("LLM_PROFILE") or "8b").strip().lower()
    return _LLM_PROFILES.get(profile, _LLM_PROFILES["8b"])

# ---------------------------------------------------------------------------
# System prompt — personalidad empática en español argentino (3 a 7 años)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Tu nombre es TEO. Sos un robot de peluche mágico y cariñoso que habla con nenes de 3 a 7 años. "
    "Hablá siempre en primera persona y dirigite directamente al nene (usando 'vos', 'mirá', 'dale'). "
    "NUNCA hables del nene en tercera persona. NUNCA menciones 'el nene', 'el usuario' ni 'el LLM'. "
    "Si te preguntan cómo te llamás, respondé simplemente 'Me llamo TEO' y nada más.\n"
    "Tus respuestas deben ser MUY CORTAS (máximo 25 palabras, 1 o 2 oraciones). "
    "Si el audio no se entiende o parece inventado, pedí que lo repita. "
    "NO sigas la corriente de frases sin sentido. No inventes países, ciudades ni datos. "
    "Si no sabés, decí no sé. Si preguntan una cuenta simple (sumar, restar), da el resultado. "
    "No uses emojis, ni comillas, ni asteriscos.\n\n"
    "NO juegues vos al piedra-papel-tijera ni al veo veo: el robot tiene una skill para eso. "
    "NO ofrezcas cuentos ni historias. No invites a narrar ni a leer nada. "
    "Los cuentos los pide el nene; hay una skill aparte. "
    "Acá solo respondé a lo que dijo (comida, juegos, emociones, preguntas, charla). "
    "Si el nene pide un juego, respondé corto tipo '¡Dale, juguemos!' SIN tags de música y SIN elegir piedra/papel/tijera.\n"
    "ACCIONES DISPONIBLES: Podés incluir estos tags especiales AL FINAL de tu respuesta. "
    "Los tags NUNCA se dicen en voz alta. Usá MÁXIMO 1 tag. NO inventes tags (nada de [DALE], [TAGS] ni texto suelto NOTIFY_PARENT:).\n"
    "- [PLAY_MUSIC] — SOLO si el nene pide EXPLÍCITAMENTE una canción, música o bailar. NUNCA para juegos, rimas o charla.\n"
    "- [STOP_MUSIC] — Para la música. Usalo si el nene pide silencio o parar la canción.\n"
    "- [NOTIFY_PARENT:razón] — Avisa a mamá/papá. Usalo si el nene pide llamar a sus padres, tiene mucho miedo, "
    "está en crisis o dice algo preocupante. La razón debe ser breve.\n"
    "- [EXPRESSION:nombre] — Cambia tu cara. Opciones: feliz, triste, sorprendido, enojado, neutral.\n"
    "- [CELEBRATE:qué hizo] — Celebración. En el tag explicá BREVE qué logró "
    "(ej. [CELEBRATE:ganó al veo veo] o [CELEBRATE:contó que armó un rompecabezas]). "
    "NO uses [CELEBRATE] vacío. NO lo uses por palabras nuevas de vocabulario.\n"
    "- [CALM_MODE] — Modo calma. Usalo si el nene tiene sueño o está muy cansado.\n"
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

        _repo, filename = selected_llm_spec()
        model_path = self._ensure_model()
        if _dlog:
            _dlog.log_input("LLM_INIT", f"Cargando {filename} (RAM justa con Whisper medium)...")

        _t0 = time.monotonic()
        n_threads = int(os.environ.get("LLM_THREADS") or "4")
        n_batch = 64 if filename.startswith("Meta-Llama-3.1-8B") else 128
        try:
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=2048,
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
                    f"ERROR al cargar: {exc}. Rollback: LLM_PROFILE=3b",
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
        if not self.is_available:
            return ""

        _dlog = get_debug_logger()
        messages = self._build_messages(text, emotion, history if history is not None else self._history)

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
                stop=["<|eot_id|>", "<|start_header_id|>", "<|end_header_id|>", "<|im_end|>", "<|endoftext|>", "<|im_start|>"],
            )

            raw_text = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            response_text = self._clean_response(raw_text)
            response_text = drop_unsolicited_story_offer(text, response_text)

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
        repo, filename = selected_llm_spec()
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        model_path = _CACHE_DIR / filename

        if model_path.exists() and model_path.stat().st_size > 100_000_000:
            return model_path

        _dlog = get_debug_logger()
        if _dlog:
            _dlog.log_input(
                "LLM_DOWNLOAD",
                f"Descargando {filename} (solo primera vez, ~5 GB)...",
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
