from __future__ import annotations

import base64
import json
import os
import platform
import queue
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
import unicodedata
import tempfile
import wave
import xml.sax.saxutils as saxutils
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover - runtime dependency check.
    raise RuntimeError("opencv-python es requerido para la PoC") from exc

try:
    import sys
    from unittest.mock import MagicMock
    sys.modules['matplotlib'] = MagicMock()
    sys.modules['matplotlib.pyplot'] = MagicMock()
except Exception:
    pass

try:
    import mediapipe as mp
except ImportError as exc:  # pragma: no cover - runtime dependency check.
    raise RuntimeError("mediapipe es requerido para la PoC") from exc

try:
    import sounddevice as sd
except ImportError as exc:  # pragma: no cover - runtime dependency check.
    raise RuntimeError("sounddevice es requerido para la PoC") from exc

try:
    import spacy
except ImportError:
    spacy = None  # type: ignore[assignment]

from debug_logger import get_debug_logger, log_action, save_named_transcript_wav
from stt_correct import polish_stt_text, spanish_vocab_checker

APP_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class WorkerMessage:
    kind: str
    payload: Any


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    low_confidence: bool = False
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


def _queue_message(message_queue: queue.Queue[WorkerMessage], kind: str, payload: Any) -> None:
    try:
        message_queue.put_nowait(WorkerMessage(kind=kind, payload=payload))
    except queue.Full:
        pass


def _queue_message_with_semaphore(
    message_queue: queue.Queue[WorkerMessage],
    message_semaphore: threading.Semaphore | None,
    kind: str,
    payload: Any,
) -> None:
    if message_semaphore is not None and not message_semaphore.acquire(blocking=False):
        return

    try:
        message_queue.put_nowait(WorkerMessage(kind=kind, payload=payload))
    except queue.Full:
        if message_semaphore is not None:
            message_semaphore.release()


def _queue_critical_message(
    message_queue: queue.Queue[WorkerMessage],
    message_semaphore: threading.Semaphore | None,
    kind: str,
    payload: Any,
    timeout: float = 10.0,
) -> None:
    """Put a high-priority message that must not be silently dropped (e.g. transcripts)."""
    if message_semaphore is not None:
        acquired = message_semaphore.acquire(timeout=timeout)
        if not acquired:
            # Last resort: try without semaphore tracking
            try:
                message_queue.put(WorkerMessage(kind=kind, payload=payload), timeout=timeout)
            except queue.Full:
                pass
            return

    try:
        message_queue.put(WorkerMessage(kind=kind, payload=payload), timeout=timeout)
    except queue.Full:
        if message_semaphore is not None:
            message_semaphore.release()


def discover_cameras(max_devices: int = 8) -> list[tuple[int, str]]:
    return [(index, f"Cámara {index}") for index in range(max_devices)]


def discover_microphones() -> list[tuple[int, str]]:
    devices: list[tuple[int, str]] = []
    try:
        for index, device in enumerate(sd.query_devices()):
            if device.get("max_input_channels", 0) > 0:
                label = f'{index}: {device.get("name", "Micrófono")}'
                devices.append((index, label))
    except Exception:
        pass
    if not devices:
        devices.append((-1, "Sin micrófono (Solo visión / ojos / rutinas)"))
    return devices


def discover_output_devices() -> list[tuple[int, str]]:
    devices: list[tuple[int, str]] = []
    try:
        for index, device in enumerate(sd.query_devices()):
            if device.get("max_output_channels", 0) > 0:
                label = f'{index}: {device.get("name", "Parlante")}'
                devices.append((index, label))
    except Exception:
        return []
    return devices


class IntentDispatcher:
    # Cosine scores from MiniLM are not comparable to spaCy similarity.
    MIN_CONFIDENCE_EMBEDDINGS: float = 0.58
    MIN_CONFIDENCE_SPACY: float = 0.45
    # Reject canned replies when two distinct intents are this close.
    CONFIDENCE_MARGIN: float = 0.08
    # Near-exact matches skip the margin/priority tie-break.
    EXACT_MATCH_THRESHOLD: float = 0.95
    _EMBEDDING_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, intents: dict[str, dict[str, Any]]) -> None:
        self.intents = intents
        self.nlp = self._load_spacy_model()
        self.current_emotion: dict[str, Any] | None = None
        self._sentence_model: Any = self._load_sentence_model()
        self._example_docs: dict[str, list[tuple[str, Any]]] = {}
        self._example_embeddings: dict[str, list[tuple[str, np.ndarray]]] = {}
        self._last_canned: dict[str, str] = {}
        self._precompute_examples()

    @property
    def MIN_CONFIDENCE(self) -> float:
        if self._sentence_model is not None:
            return self.MIN_CONFIDENCE_EMBEDDINGS
        return self.MIN_CONFIDENCE_SPACY

    @classmethod
    def from_file(cls, path: Path) -> "IntentDispatcher":
        if path.exists():
            intents = json.loads(path.read_text(encoding="utf-8"))
        else:
            intents = {
                "greeting": {
                    "examples": ["hola", "buenos dias", "hey"],
                    "response": "Hola, estoy escuchando.",
                    "emotions": ["feliz", "neutral"],
                    "emotion_threshold": 0.14,
                },
                "play": {
                    "examples": ["quiero jugar", "abrir juego", "empezar juego"],
                    "response": "Modo juego detectado.",
                    "emotions": ["feliz"],
                    "emotion_threshold": 0.12,
                },
            }
        return cls(intents=intents)

    def set_current_emotion(self, label: str | None, score: float | None = None) -> None:
        if label is None:
            self.current_emotion = None
        else:
            self.current_emotion = {"label": label, "score": float(score or 0.0)}

    def _load_spacy_model(self):
        return None

    def _load_sentence_model(self) -> Any:
        return None

    def _precompute_examples(self) -> None:
        self._example_docs = {name: [] for name in self.intents}
        self._example_embeddings = {name: [] for name in self.intents}

    def dispatch(self, text: str, emotion: dict[str, Any] | None = None) -> dict[str, Any]:
        _dlog = get_debug_logger()
        candidate_text = (text or "").strip()
        if not candidate_text:
            return {"intent_name": "unknown", "confidence": 0.0, "response": ""}

        if _dlog:
            _dlog.log_input("INTENT_DISPATCH", f"text=\"{candidate_text}\"")
        _t0 = time.monotonic()

        keyword_intent = self._keyword_intent(candidate_text)
        if keyword_intent == "stop_music_request":
            if _dlog:
                _dlog.log_output(
                    "INTENT_DISPATCH",
                    "keyword=stop_music_request",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return {
                "intent_name": "stop_music_request",
                "confidence": 0.95,
                "response": "Listo, paro la música.",
                "pilar": "general",
            }

        if keyword_intent and keyword_intent in self.intents:
            intent_definition = self.intents[keyword_intent]
            result = {
                "intent_name": keyword_intent,
                "confidence": 0.92,
                "response": self._pick_response(
                    keyword_intent, intent_definition.get("response", "")
                ),
                "pilar": intent_definition.get("pilar", "general"),
            }
            if _dlog:
                _dlog.log_output(
                    "INTENT_DISPATCH",
                    f"intent={keyword_intent} conf=0.920 top2=0.000",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return result

        if _dlog:
            _dlog.log_output(
                "INTENT_DISPATCH",
                "unknown",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )
        return {
            "intent_name": "unknown",
            "confidence": 0.0,
            "response": "",
        }

    def _score_intents(self, candidate_text: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        query_embedding = self._encode_query(candidate_text)
        source_doc = None
        if query_embedding is None and self.nlp is not None:
            source_doc = self.nlp(candidate_text)

        for intent_name in self.intents:
            best = 0.0
            if query_embedding is not None:
                for example_text, example_vec in self._example_embeddings.get(intent_name, []):
                    cosine = float(np.dot(query_embedding, example_vec))
                    if np.isnan(cosine):
                        cosine = 0.0
                    lexical = self._token_overlap(candidate_text, example_text)
                    best = max(best, max(0.0, min(1.0, max(cosine, lexical))))
            else:
                for _example_text, example_doc in self._example_docs.get(intent_name, []):
                    best = max(best, self._similarity(source_doc, example_doc))
            scores[intent_name] = best
        return scores

    def _encode_query(self, text: str) -> np.ndarray | None:
        if self._sentence_model is None:
            return None
        try:
            vector = self._sentence_model.encode(
                [text],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            return np.asarray(vector, dtype=np.float32)
        except Exception:
            return None

    def _intent_priority(self, intent_name: str) -> int:
        try:
            return int(self.intents.get(intent_name, {}).get("priority", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _keyword_intent(text: str) -> str | None:
        """Skills con frases muy claras: no depender del umbral de embeddings."""
        from session_policy import is_clear_keyword_intent

        return is_clear_keyword_intent(text)

    _THIN_INTENTS = frozenset({
        "emotion_sad",
        "emotion_angry",
        "emotion_happy",
        "emotion_fear",
        "crisis_cry",
        "routine_ack",
        "routine_resist",
        "routine_hygiene",
        "routine_tidy",
        "call_parent",
        "frustration_support",
    })
    _EMOTION_HINT = re.compile(
        r"triste|enojad|furios|llor|asust|miedo|cuco|feliz|content|nervios|solo|sola",
        re.IGNORECASE,
    )

    def _utterance_too_thin(self, text: str, intent_name: str) -> bool:
        """Sí/no/dale no deben reactivar el mismo intent emocional o de rutina."""
        if intent_name not in self._THIN_INTENTS:
            return False
        folded = self._normalize_text(text)
        words = folded.split()
        if self._EMOTION_HINT.search(folded):
            return False
        if len(words) <= 2:
            return True
        return False

    def _pick_response(self, intent_name: str, response_field: Any) -> str:
        if isinstance(response_field, list):
            options = [str(item).strip() for item in response_field if str(item).strip()]
            if not options:
                return ""
            last = self._last_canned.get(intent_name)
            if last and len(options) > 1:
                options = [item for item in options if item != last] or options
            chosen = random.choice(options)
            self._last_canned[intent_name] = chosen
            return chosen
        return str(response_field or "")

    def _similarity(self, left_doc, right_doc) -> float:
        lexical_score = self._token_overlap(left_doc.text, right_doc.text)
        try:
            score = float(left_doc.similarity(right_doc))
            if np.isnan(score):
                return lexical_score
            return max(0.0, min(1.0, max(score, lexical_score)))
        except Exception:
            return lexical_score

    @staticmethod
    def _token_overlap(left_text: str, right_text: str) -> float:
        left_tokens = {token.lower() for token in re.findall(r"\w+", IntentDispatcher._normalize_text(left_text))}
        right_tokens = {token.lower() for token in re.findall(r"\w+", IntentDispatcher._normalize_text(right_text))}
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return normalized.lower().strip()


class TextSanitizer:
    def __init__(self) -> None:
        # Pre-cargar scrubadub en init para evitar penalidad de 11s en primer uso.
        self._scrubadub = None
        try:
            import scrubadub
            self._scrubadub = scrubadub
        except ImportError:
            pass

    def sanitize(self, text: str) -> dict[str, Any]:
        original_text = text or ""
        findings: list[dict[str, Any]] = []
        sanitized_text = original_text
        replacement_terms: list[str] = []

        try:
            if self._scrubadub is None:
                raise ImportError("scrubadub no disponible")
            scrubber = self._scrubadub.Scrubber()
            filth_items = list(scrubber.iter_filth(original_text))
            if filth_items:
                spans = []
                for filth in filth_items:
                    start = self._get_attr(filth, ("beg", "start", "begin"))
                    end = self._get_attr(filth, ("end", "stop"))
                    filth_text = getattr(filth, "text", "")
                    filth_type = getattr(filth, "type_name", filth.__class__.__name__.lower())
                    findings.append({"type": filth_type, "value": None})
                    if isinstance(start, int) and isinstance(end, int) and end > start:
                        spans.append((start, end))
                    if isinstance(filth_text, str) and filth_text:
                        replacement_terms.append(filth_text)

                sanitized_text = self._remove_spans(original_text, spans)
                if sanitized_text == original_text and replacement_terms:
                    sanitized_text = original_text
                    for term in replacement_terms:
                        sanitized_text = re.sub(re.escape(term), " ", sanitized_text)
                    sanitized_text = re.sub(r"\s+", " ", sanitized_text)
        except Exception:
            regex_findings, sanitized_text = self._regex_fallback(original_text)
            findings.extend(regex_findings)

        return {"sanitized_text": sanitized_text.strip(), "redactions": findings}

    @staticmethod
    def _get_attr(obj: Any, names: tuple[str, ...]) -> Any:
        for name in names:
            value = getattr(obj, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
        if not spans:
            return text
        pieces = []
        cursor = 0
        for start, end in sorted(spans):
            if start > cursor:
                pieces.append(text[cursor:start])
            cursor = max(cursor, end)
        if cursor < len(text):
            pieces.append(text[cursor:])
        return re.sub(r"\s+", " ", "".join(pieces))

    def _regex_fallback(self, text: str) -> tuple[list[dict[str, Any]], str]:
        patterns = {
            "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            "phone": r"\b(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){7,14}\b",
            "id": r"\b\d{6,12}\b",
        }
        findings: list[dict[str, Any]] = []
        sanitized_text = text
        for name, pattern in patterns.items():
            matches = list(re.finditer(pattern, sanitized_text))
            if matches:
                findings.extend({"type": name, "value": None} for _ in matches)
                sanitized_text = re.sub(pattern, " ", sanitized_text)
        sanitized_text = re.sub(r"\s+", " ", sanitized_text)
        return findings, sanitized_text


class EmotionReactor:
    """Evalúa el contexto emocional y decide si interrumpir el flujo normal
    de intenciones para activar un protocolo de crisis o regulación emocional.

    Implementa #EPIC-005 CA#1 (reacción empática) y CA#2 (pausas adaptativas).
    """

    # Emociones que activan el protocolo de crisis y sus umbrales mínimos
    CRISIS_EMOTIONS: dict[str, float] = {
        "triste": 0.45,
        "enojado": 0.50,
    }

    # Emociones que requieren silencio extendido para que el niño se exprese
    EXTENDED_SILENCE_EMOTIONS: frozenset[str] = frozenset({"triste", "enojado"})

    # Umbrales de silencio (LATENCIA: ver docs/LATENCIA_AUDIO_CAMARA.md punto 1)
    # 0.7s / 1.6s cortaba frases a mitad. Rollback de latencia: 0.7 / 1.6.
    NORMAL_SILENCE: float = 1.2
    EXTENDED_SILENCE: float = 3.0

    # Respuestas de crisis (fallback si no hay intención matcheada)
    _CRISIS_RESPONSES: dict[str, str] = {
        "triste": (
            "Veo que estás triste. Está bien sentirse así. "
            "Estoy acá con vos. ¿Querés que respiremos juntos?"
        ),
        "enojado": (
            "Entiendo que estás enojado. Está bien sentirse así a veces. "
            "¿Querés que hagamos respiraciones juntos para calmarnos?"
        ),
    }

    def evaluate(
        self,
        emotion_context: dict[str, Any] | None,
        intent_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Evalúa si se debe activar protocolo de crisis.

        Si la emoción indica crisis y la intención detectada no es ya una
        intención emocional, reemplaza el resultado con una respuesta de
        contención.

        Returns:
            intent_result modificado si hay crisis, o el original.
        """
        if not emotion_context:
            return intent_result

        label = str(emotion_context.get("label", "")).lower()
        score = float(emotion_context.get("score", 0.0))

        # Verificar si la emoción alcanza el umbral de crisis
        threshold = self.CRISIS_EMOTIONS.get(label)
        if threshold is None or score < threshold:
            return intent_result

        # Si la intención ya es emocional, no sobrescribir
        intent_name = intent_result.get("intent_name", "")
        emotional_intents = {
            "emotion_sad", "emotion_angry", "emotion_happy",
            "crisis_cry", "regulation_breathing", "yoga_request",
        }
        if intent_name in emotional_intents:
            # Marcar como crisis pero mantener la intención original
            intent_result["is_crisis"] = True
            return intent_result

        # Override: forzar respuesta de crisis
        crisis_intent = "emotion_angry" if label == "enojado" else "emotion_sad"
        return {
            "intent_name": crisis_intent,
            "confidence": score,
            "response": self._CRISIS_RESPONSES.get(label, self._CRISIS_RESPONSES["triste"]),
            "pilar": "emocional",
            "is_crisis": True,
        }

    def get_silence_threshold(self, emotion_context: dict[str, Any] | None) -> float:
        """Retorna el umbral de silencio adaptado a la emoción.

        Cuando el niño está triste o enojado, se extiende el tiempo de
        espera para que pueda terminar de expresarse a su ritmo
        (#EPIC-005 CA#2).
        """
        if not emotion_context:
            return self.NORMAL_SILENCE

        label = str(emotion_context.get("label", "")).lower()
        if label in self.EXTENDED_SILENCE_EMOTIONS:
            return self.EXTENDED_SILENCE
        return self.NORMAL_SILENCE


class CameraWorker:
    EMOTION_FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
        "feliz": {
            "mouthSmileLeft": 0.5,
            "mouthSmileRight": 0.5,
        },
        "triste": {
            "mouthFrownLeft": 0.4,
            "mouthFrownRight": 0.4,
            "browInnerUp": 0.2,
        },
        "sorprendido": {
            "jawOpen": 0.5,
            "eyeWideLeft": 0.25,
            "eyeWideRight": 0.25,
        },
        "enojado": {
            "browDownLeft": 0.35,
            "browDownRight": 0.35,
            "noseSneerLeft": 0.15,
            "noseSneerRight": 0.15,
        },
    }
    EMOTION_MIN_SCORES: dict[str, float] = {
        "feliz": 0.18,
        "triste": 0.16,
        "sorprendido": 0.10,
        "enojado": 0.16,
    }
    NEUTRAL_SCORE_THRESHOLD = 0.14

    def __init__(
        self,
        camera_index: int,
        frame_queue: queue.Queue[object],
        frame_semaphore: threading.Semaphore | None,
        message_queue: queue.Queue[WorkerMessage],
        message_semaphore: threading.Semaphore | None,
    ) -> None:
        self.camera_index = camera_index
        self.frame_queue = frame_queue
        self.frame_semaphore = frame_semaphore
        self.message_queue = message_queue
        self.message_semaphore = message_semaphore
        self._stop_event = threading.Event()
        self.models_loaded_event = threading.Event()
        self._thread: threading.Thread | None = None
        # LATENCIA punto 7: emoción por cámara es la feature de menor prioridad.
        # Antes: 3 fps. Revertir a 3 si se necesita la cara más fluida en el dashboard.
        self.frame_rate = 1
        # False = solo preview (sin MediaPipe). True restaura detección de emoción.
        # Ver docs/LATENCIA_AUDIO_CAMARA.md
        self.infer_emotion = False

    def start(self) -> None:
        log_action("CameraWorker", f"inicio (cámara={self.camera_index})")
        self._thread = threading.Thread(target=self._run, name="CameraWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        log_action("CameraWorker", "deteniendo...")
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        log_action("CameraWorker", "detenido")

    def _run(self) -> None:
        capture = None
        face_mesh = None
        tasks_landmarker = None
        mp_drawing = None
        mp_face_mesh = None
        face_mesh_enabled = False
        tasks_face_enabled = False
        last_emotion_log_ts = 0.0
        last_emotion_label = ""
        log_action("CameraWorker", "tarea _run comenzada")

        if self.camera_index is None or int(self.camera_index) < 0:
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "log",
                "Cámara desactivada (headless / sin OpenCV). Audio sigue.",
            )
            self.models_loaded_event.set()
            while not self._stop_event.is_set():
                time.sleep(0.2)
            log_action("CameraWorker", "tarea _run finalizada (sin cámara)")
            return

        try:
            # Auto-detect capture backend: DirectShow on Windows, V4L2 on Linux/RPi
            if sys.platform.startswith("win"):
                capture_backend = getattr(cv2, "CAP_DSHOW", 0)
            else:
                capture_backend = getattr(cv2, "CAP_V4L2", 0)
            capture = cv2.VideoCapture(self.camera_index, capture_backend)
            if not capture.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {self.camera_index}")
            # LATENCIA punto 7: resolución mínima. Antes 640x480.
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

            # LATENCIA punto 7: MediaPipe apagado por defecto (infer_emotion=False).
            if self.infer_emotion:
                if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
                    mp_face_mesh = mp.solutions.face_mesh
                    mp_drawing = mp.solutions.drawing_utils
                    drawing_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1)
                    connection_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1)
                    face_mesh = mp_face_mesh.FaceMesh(
                        static_image_mode=False,
                        max_num_faces=1,
                        refine_landmarks=False,
                        min_detection_confidence=0.5,
                        min_tracking_confidence=0.5,
                    )
                    face_mesh_enabled = True
                    _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", "MediaPipe FaceMesh habilitado")
                    _dlog = get_debug_logger()
                    if _dlog:
                        _dlog.log_output("MEDIAPIPE", "FaceMesh cargado")
                else:
                    tasks_landmarker = self._create_tasks_face_landmarker()
                    if tasks_landmarker is not None:
                        tasks_face_enabled = True
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            "MediaPipe Tasks Face Landmarker habilitado",
                        )
                    else:
                        raise RuntimeError(
                            "No se pudo inicializar deteccion facial. "
                            "Instala/usa una version de MediaPipe compatible o habilita descarga del modelo face_landmarker.task."
                        )
            else:
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    "Cámara en modo preview (emoción/MediaPipe desactivado)",
                )

            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "status",
                {"camera": f"{self.camera_index} activa"},
            )
            self.models_loaded_event.set()
            _cam_dlog = get_debug_logger()
            if _cam_dlog:
                _cam_dlog.log_output("CAMERA", "Modelos de cámara listos, captura iniciada")
            log_action("CameraWorker", "captura iniciada, modelos listos")
            # Throttle processing to configured frame rate
            frame_interval = 1.0 / float(getattr(self, "frame_rate", 5))
            last_frame_ts = 0.0

            while not self._stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"Aviso: no se pudo leer frame de la cámara {self.camera_index}",
                    )
                    time.sleep(0.05)
                    continue

                now_ts = time.monotonic()
                if now_ts - last_frame_ts < frame_interval:
                    # Sleep briefly to avoid busy-looping and reduce CPU
                    time.sleep(max(0.001, frame_interval - (now_ts - last_frame_ts)))
                    continue
                last_frame_ts = now_ts

                if not self.infer_emotion:
                    self._push_frame(frame)
                elif face_mesh_enabled and face_mesh is not None and mp_drawing is not None and mp_face_mesh is not None:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    face_mesh.process(rgb_frame)
                    self._push_frame(frame)
                elif tasks_face_enabled and tasks_landmarker is not None:
                    annotated_frame, emotion_payload = self._process_tasks_frame(tasks_landmarker, frame)
                    self._push_frame(annotated_frame)

                    if emotion_payload is not None:
                        now = time.monotonic()
                        emotion_label = emotion_payload.get("label", "desconocida")
                        emotion_score = float(emotion_payload.get("score", 0.0))
                        if (now - last_emotion_log_ts) >= 3.0 or emotion_label != last_emotion_label:
                            if emotion_label != last_emotion_label:
                                log_action(
                                    "CameraWorker",
                                    f"emoción={emotion_label} ({emotion_score:.2f})",
                                )
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "emotion",
                                {
                                    "label": emotion_label,
                                    "score": emotion_score,
                                },
                            )
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "status",
                                {
                                    "camera": f"{self.camera_index} activa",
                                    "emotion": f"{emotion_label} ({emotion_score:.2f})",
                                },
                            )
                            last_emotion_log_ts = now
                            last_emotion_label = emotion_label
                else:
                    self._push_frame(frame)

                # LATENCIA punto 7: ceder CPU al audio/Whisper (antes 0.005).
                time.sleep(0.05)

        except Exception as exc:
            self.models_loaded_event.set()
            log_action("CameraWorker", f"ERROR: {exc}")
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en cámara: {exc}")
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "status",
                {"camera": "error"},
            )
        finally:
            self.models_loaded_event.set()
            if face_mesh is not None:
                face_mesh.close()
            if tasks_landmarker is not None:
                tasks_landmarker.close()
            if capture is not None:
                capture.release()
            log_action("CameraWorker", "tarea _run finalizada")

    def _create_tasks_face_landmarker(self):
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            model_path = self._ensure_face_landmarker_model()
            base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
            options = vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
            )
            return vision.FaceLandmarker.create_from_options(options)
        except Exception as exc:
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "log",
                f"Error inicializando Face Landmarker (Tasks): {exc}",
            )
            return None

    def _ensure_face_landmarker_model(self) -> Path:
        candidates = [
            Path(__file__).resolve().parent / "models" / "face_landmarker.task",
            Path.cwd() / "models" / "face_landmarker.task",
        ]

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(Path(getattr(sys, "_MEIPASS")) / "models" / "face_landmarker.task")

        for candidate in candidates:
            if candidate.exists():
                return candidate

        cache_dir = Path.home() / ".edge_ai_models" / "mediapipe"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / "face_landmarker.task"
        if target.exists():
            return target

        model_url = (
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/1/face_landmarker.task"
        )
        _queue_message_with_semaphore(
            self.message_queue,
            self.message_semaphore,
            "log",
            "Descargando modelo face_landmarker.task (solo primera vez)...",
        )
        urllib.request.urlretrieve(model_url, target)
        return target

    def _process_tasks_frame(self, tasks_landmarker: Any, frame: np.ndarray) -> tuple[np.ndarray, dict[str, Any] | None]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int(time.monotonic() * 1000)
        result = tasks_landmarker.detect_for_video(mp_image, timestamp_ms)

        # Reuse the frame buffer directly to avoid an expensive copy.
        # The caller does not use `frame` after this function returns.
        annotated = frame
        emotion_payload: dict[str, Any] | None = None

        face_landmarks = getattr(result, "face_landmarks", None) or []
        if face_landmarks:
            first_face = face_landmarks[0]
            self._draw_face_bbox(annotated, first_face)

            blendshapes = getattr(result, "face_blendshapes", None) or []
            emotion_payload = self._infer_emotion_from_blendshapes(blendshapes[0] if blendshapes else [])
            label = emotion_payload.get("label", "desconocida")
            score = float(emotion_payload.get("score", 0.0))
            cv2.putText(
                annotated,
                f"Emocion: {label} ({score:.2f})",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                annotated,
                "No se detecta rostro",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 165, 255),
                2,
                cv2.LINE_AA,
            )

        return annotated, emotion_payload

    @staticmethod
    def _draw_face_bbox(frame: np.ndarray, landmarks: Any) -> None:
        h, w = frame.shape[:2]
        xs = [float(point.x) for point in landmarks]
        ys = [float(point.y) for point in landmarks]
        if not xs or not ys:
            return

        x_min = max(0, int(min(xs) * w))
        y_min = max(0, int(min(ys) * h))
        x_max = min(w - 1, int(max(xs) * w))
        y_max = min(h - 1, int(max(ys) * h))
        cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), (0, 255, 255), 2)

    @staticmethod
    def _infer_emotion_from_blendshapes(blendshapes: Any) -> dict[str, Any]:
        scores: dict[str, float] = {}
        for item in blendshapes:
            name = str(getattr(item, "category_name", ""))
            score = float(getattr(item, "score", 0.0))
            if name:
                scores[name] = score

        def weighted_score(weights: dict[str, float]) -> float:
            weighted_total = 0.0
            weight_sum = 0.0
            for feature_name, feature_weight in weights.items():
                weighted_total += scores.get(feature_name, 0.0) * feature_weight
                weight_sum += feature_weight
            if weight_sum <= 0.0:
                return 0.0
            return float(weighted_total / weight_sum)

        emotions = {name: weighted_score(weights) for name, weights in CameraWorker.EMOTION_FEATURE_WEIGHTS.items()}

        label = max(emotions, key=emotions.get) if emotions else "neutral"
        score = emotions.get(label, 0.0)
        if score < CameraWorker.EMOTION_MIN_SCORES.get(label, CameraWorker.NEUTRAL_SCORE_THRESHOLD):
            return {"label": "neutral", "score": 1.0 - score}
        return {"label": label, "score": score}

    def _push_frame(self, frame: np.ndarray) -> None:
        try:
            if self.frame_semaphore is not None and not self.frame_semaphore.acquire(blocking=False):
                return
            self.frame_queue.put_nowait(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        except queue.Full:
            if self.frame_semaphore is not None:
                self.frame_semaphore.release()
            pass


def whisper_beam_size() -> int:
    """Default 1. Rollback de calidad STT: WHISPER_BEAM=5."""
    try:
        return max(1, int(os.environ.get("WHISPER_BEAM") or "1"))
    except ValueError:
        return 1


STT_SAMPLE_RATE = 16000
# USB de esta Pi: ALSA rechaza 16 kHz (PaErrorCode -9997) y abre a 48 kHz.
PI_MIC_CAPTURE_RATE = 48000
# ~16 s de bloques de 128 ms. 32 se llenaba y el VAD tomaba huecos por silencio.
AUDIO_QUEUE_MAXSIZE = 128


def vad_log_label(mode: str) -> str:
    """Prefijo de log: en aarch64 el VAD real es energía, no Silero."""
    return "silero-vad" if mode == "silero" else "energy-vad"


def enqueue_mic_block(
    audio_queue: queue.Queue,
    audio_block: np.ndarray,
    drop_hits: list[int],
) -> None:
    """Callback-safe: copy ya hecho; sin I/O. Cola llena = drop, no xrun."""
    try:
        audio_queue.put_nowait(audio_block)
    except queue.Full:
        drop_hits[0] += 1


def apply_capture_drops(
    speech_active: bool,
    drop_hits: int,
    drops_seen: int,
    silence_seconds: float,
) -> tuple[float, int]:
    """Huecos de cola no cuentan como silencio (dispara el hangover)."""
    if drop_hits <= drops_seen:
        return silence_seconds, drops_seen
    if speech_active:
        silence_seconds = 0.0
    return silence_seconds, drop_hits


def pi_mic_capture_rate() -> int:
    """En la Pi el mic actual es 48 kHz. En Windows la PoC sigue a 16 kHz."""
    if sys.platform.startswith("linux"):
        return PI_MIC_CAPTURE_RATE
    return STT_SAMPLE_RATE


def downsample_capture_to_stt(
    block: np.ndarray,
    capture_sr: int,
    target_sr: int = STT_SAMPLE_RATE,
) -> np.ndarray:
    """48 kHz → 16 kHz con promedio de 3 samples (anti-alias barato). Fuera del callback."""
    arr = np.asarray(block, dtype=np.float32).reshape(-1)
    if capture_sr == target_sr or arr.size == 0:
        return arr
    if capture_sr == 48000 and target_sr == 16000:
        n = (arr.size // 3) * 3
        if n == 0:
            return arr[:0].copy()
        return arr[:n].reshape(-1, 3).mean(axis=1).astype(np.float32)
    return SpeechWorker._resample_audio(arr, capture_sr, target_sr)


def pcm_s16le_to_float32(block: np.ndarray) -> np.ndarray:
    arr = np.asarray(block).reshape(-1)
    if arr.dtype != np.int16:
        arr = arr.astype(np.int16, copy=False)
    return arr.astype(np.float32) * (1.0 / 32768.0)


def stt_block_duration_seconds(
    n_samples: int,
    sample_rate: int = STT_SAMPLE_RATE,
) -> float:
    if sample_rate <= 0 or n_samples <= 0:
        return 0.0
    return float(n_samples) / float(sample_rate)


def capture_hop_seconds(platform_name: str | None = None) -> float:
    name = sys.platform if platform_name is None else platform_name
    if str(name).startswith("linux"):
        return 960.0 / 48000.0
    return 0.128


def vad_pre_roll_blocks(hop_seconds: float, pre_roll_seconds: float = 1.0) -> int:
    hop = max(float(hop_seconds), 1e-6)
    return max(1, int(round(pre_roll_seconds / hop)))


def vad_circular_maxlen(hop_seconds: float, window_seconds: float = 6.0) -> int:
    hop = max(float(hop_seconds), 1e-6)
    return max(8, int(round(window_seconds / hop)))


def find_supported_input_config(
    device_index: int | None,
    preferred_sr: int = STT_SAMPLE_RATE,
) -> tuple[int, str, int]:
    """Sample rate/dtype/channels that the input device accepts.

    Cheap USB PnP mics reject 16000 Hz (PaErrorCode -9997) and only
    open at 48000/44100.
    """
    rates: list[int] = []
    for sr in (preferred_sr, 48000, 44100, 32000, 22050, 16000):
        if sr not in rates:
            rates.append(sr)
    dtypes = ("float32", "int16")
    channel_options = (1, 2)
    for sr in rates:
        for dtype in dtypes:
            for ch in channel_options:
                try:
                    sd.check_input_settings(
                        device=device_index,
                        samplerate=float(sr),
                        channels=ch,
                        dtype=dtype,
                    )
                    return sr, dtype, ch
                except Exception:
                    continue
    return preferred_sr, "float32", 1


def mic_block_to_stt(
    indata: np.ndarray,
    capture_sr: int,
    target_sr: int = STT_SAMPLE_RATE,
) -> np.ndarray:
    """Mono float32 at target_sr for VAD/Whisper/Vosk."""
    arr = np.asarray(indata)
    if arr.ndim == 2:
        arr = arr[:, 0]
    else:
        arr = arr.reshape(-1)
    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        arr = arr.astype(np.float32) / float(info.max)
    else:
        arr = arr.astype(np.float32, copy=False)
    if capture_sr != target_sr:
        arr = SpeechWorker._resample_audio(arr, capture_sr, target_sr)
    return arr


class AudioWorker:
    # Tope duro de captura: silencio (VAD) o este máximo, lo que ocurra primero.
    # LATENCIA punto 10: 8.0. Rollback (cuentos largos): 15.0.
    MAX_LISTEN_SECONDS: float = 8.0

    def __init__(
        self,
        microphone_device_index: int,
        message_queue: queue.Queue[WorkerMessage],
        message_semaphore: threading.Semaphore | None,
        intent_dispatcher: IntentDispatcher,
        camera_ready_event: threading.Event | None = None,
        speech_worker: Any = None,
        telemetry: Any = None,
        vocabulary_tracker: Any = None,
        routine_scheduler: Any = None,
        fallback_llm: Any = None,
        cloud_mode: bool = False,
        cloud_stt: Any = None,
        cloud_llm: Any = None,
        eye_display: Any = None,
    ) -> None:
        self.microphone_device_index = microphone_device_index
        self.message_queue = message_queue
        self.message_semaphore = message_semaphore
        self.intent_dispatcher = intent_dispatcher
        self.camera_ready_event = camera_ready_event
        self.speech_worker = speech_worker
        self.sanitizer = TextSanitizer()
        self.emotion_reactor = EmotionReactor()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._echo_mute_until = 0.0
        self._alsa_capture: Any = None
        self._input_stream: Any = None

        # New subsystems for pillar coverage
        self.telemetry = telemetry
        self.vocabulary_tracker = vocabulary_tracker
        self.routine_scheduler = routine_scheduler

        # Fallback LLM for unknown intents (#EPIC-LLM)
        self.fallback_llm = fallback_llm

        # Cloud mode (#CLOUD-001)
        self.cloud_mode = cloud_mode
        self.cloud_stt = cloud_stt
        self.cloud_llm = cloud_llm

        # Eye display reference for action tags (#LLM-SKILLS)
        self.eye_display = eye_display
        self._set_eyes("zzz")

        # Robot state for notifications (#LLM-SKILLS)
        try:
            from api_server import robot_state as _rs
            self._robot_state = _rs
        except ImportError:
            self._robot_state = None

        # Game engine for multi-turn interactive games (#EPIC-006)
        try:
            from game_engine import GameEngine
            self.game_engine: Any = GameEngine()
        except ImportError:
            self.game_engine = None

        try:
            from story_engine import StoryEngine
            self.story_engine: Any = StoryEngine()
        except ImportError:
            self.story_engine = None

        try:
            from yoga_engine import YogaEngine
            self.yoga_engine: Any = YogaEngine()
        except ImportError:
            self.yoga_engine = None

        try:
            from hardware import get_companion
            self.companion: Any = get_companion()
        except Exception:
            self.companion = None

        from session_policy import IntentMute, PlaytimeGuard
        self.playtime_guard = PlaytimeGuard(limit_minutes=0)
        self.intent_mute = IntentMute()

        from conversation_memory import ConversationMemory
        self.conversation_memory = ConversationMemory()
        self._story_generation = 0
        self._story_lock = threading.Lock()

        from parent_alerts import VocabularyParentAlerter
        self._vocab_alerter = VocabularyParentAlerter()

    def start(self) -> None:
        log_action("AudioWorker", f"inicio (mic={self.microphone_device_index})")
        self._thread = threading.Thread(target=self._run, name="AudioWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        log_action("AudioWorker", "deteniendo...")
        self._stop_event.set()
        cap = self._alsa_capture
        if cap is not None:
            try:
                cap.stop()
            except Exception:
                pass
        stream = self._input_stream
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._flush_vocab_parent_alert(force_session=True)
        log_action("AudioWorker", "detenido")

    def _set_eyes(self, expression: str) -> None:
        display = self.eye_display
        if display is None or not hasattr(display, "set_expression"):
            return
        try:
            display.set_expression(expression)
        except Exception:
            pass

    def _thinking_eyes(self, on: bool) -> None:
        display = self.eye_display
        if display is None or not hasattr(display, "set_expression"):
            return
        try:
            if on:
                self._eyes_before_think = display.get_expression()
                display.set_expression("pensando")
                return
            prev = getattr(self, "_eyes_before_think", None)
            self._eyes_before_think = None
            if not prev or prev == "pensando":
                prev = "escuchando"
            display.set_expression(prev)
        except Exception:
            pass

    def _notify_vocab_parent(self, message: str) -> None:
        if not message or self._robot_state is None:
            return
        self._robot_state.push_notification("vocabulario", message)

    def _flush_vocab_parent_alert(self, force_session: bool = False) -> None:
        try:
            msg = (
                self._vocab_alerter.flush_session()
                if force_session
                else self._vocab_alerter.poll()
            )
        except Exception:
            return
        if msg:
            self._notify_vocab_parent(msg)

    STORY_CHECKIN_SECONDS = 6.0
    STORY_REFLECT_FALLBACK = "¿Qué parte te gustó más?"
    STORY_REFLECT_COMMENT_FALLBACK = "Qué lindo lo que contaste."

    def _invalidate_story_timer(self) -> None:
        self._story_generation += 1

    def _publish_story_status(self) -> None:
        reading = None
        if self.story_engine is not None:
            reading = self.story_engine.now_reading()
        if self._robot_state is not None:
            self._robot_state.currently_reading = reading

    def _remember_turn(self, user_text: str, payload: dict[str, Any], spoken_response: str) -> None:
        if payload.get("intent_name") == "story_reading" and payload.get("story_chunk"):
            return
        user = (user_text or "").strip()
        assistant = (spoken_response or "").strip()
        closing = str(payload.get("story_closing") or "").strip()
        if closing and closing not in assistant:
            assistant = (assistant + " " + closing).strip()
        if user and assistant:
            self.conversation_memory.add_turn(user, assistant)

    def _arm_story_timer(self) -> None:
        gen = self._story_generation
        seconds = self.STORY_CHECKIN_SECONDS

        def _wait() -> None:
            time.sleep(seconds)
            if gen != self._story_generation:
                return
            if self.story_engine is None or not self.story_engine.is_waiting_for_child:
                return
            with self._story_lock:
                if gen != self._story_generation:
                    return
                if not self.story_engine.is_waiting_for_child:
                    return
                payload = self.story_engine.advance_silence()
            self._speak_story_payload(payload, generation=gen)

        threading.Thread(target=_wait, name="StoryCheckin", daemon=True).start()

    def _speak_story_payload(self, payload: dict[str, Any], generation: int | None) -> None:
        if generation is None:
            generation = self._story_generation
        if self.speech_worker is None:
            self._publish_story_status()
            return

        def _still() -> bool:
            return generation == self._story_generation

        intro = self._strip_unspeakable(str(payload.get("response") or ""))
        if payload.get("intent_name") == "story_reflect_answer" and not intro:
            intro = self.STORY_REFLECT_COMMENT_FALLBACK
        if intro and _still():
            self.speech_worker.speak_and_wait(intro, timeout=60.0)
        chunk = self._strip_unspeakable(str(payload.get("story_chunk") or ""))
        if chunk and _still():
            self.speech_worker.speak_and_wait(chunk, timeout=180.0)

        if payload.get("story_need_reflection") and _still():
            question = self._story_reflection_question(payload)
            if question:
                self.speech_worker.speak_and_wait(question, timeout=60.0)
            if _still():
                self._arm_story_timer()
        elif payload.get("story_checkin") and _still():
            checkin = self._strip_unspeakable(str(payload.get("story_checkin")))
            if checkin:
                self.speech_worker.speak_and_wait(checkin, timeout=30.0)
            if _still():
                self._arm_story_timer()
        else:
            closing = self._strip_unspeakable(str(payload.get("story_closing") or ""))
            if closing and _still() and closing != intro:
                self.speech_worker.speak_and_wait(closing, timeout=60.0)

        self._publish_story_status()

    def _story_reflection_question(self, payload: dict[str, Any]) -> str:
        title = payload.get("story_title") or "el cuento"
        digest = payload.get("story_digest") or ""
        prompt = (
            f"Leímos el cuento '{title}'. Texto: {digest}. "
            "Hacé UNA pregunta corta para que el nene piense el cuento. "
            "No narres. Máximo 15 palabras."
        )
        hist = self.conversation_memory.messages()
        reply = ""
        try:
            if self.cloud_mode and self.cloud_llm is not None and self.cloud_llm.is_available:
                reply = self.cloud_llm.generate(prompt, None, history=hist) or ""
            elif self.fallback_llm is not None and getattr(self.fallback_llm, "is_available", False):
                reply = self.fallback_llm.generate(prompt, None, history=hist) or ""
        except Exception:
            reply = ""
        cleaned = self._strip_unspeakable(reply)
        return cleaned or self.STORY_REFLECT_FALLBACK

    def stop_story_from_api(self) -> None:
        self._invalidate_story_timer()
        if self.story_engine is not None:
            self.story_engine.cancel()
        self._publish_story_status()

    def play_story_from_api(self, story_id: str | None) -> bool:
        if not story_id or self.story_engine is None:
            return False
        if self.speech_worker is not None:
            self.speech_worker.stop_music()
        self._invalidate_story_timer()
        with self._story_lock:
            payload = self.story_engine.start_by_id(story_id)
        if not payload.get("story_chunk"):
            self._publish_story_status()
            return False
        gen = self._story_generation

        def _run() -> None:
            self._speak_story_payload(payload, generation=gen)

        threading.Thread(target=_run, name="StoryPlay", daemon=True).start()
        return bool(payload.get("story_chunk") or payload.get("response"))

    def _run(self) -> None:
        stt_rate = STT_SAMPLE_RATE
        capture_sr = pi_mic_capture_rate()
        hop_seconds = capture_hop_seconds()
        log_action("AudioWorker", "tarea _run comenzada")
        self._set_eyes("zzz")
        block_size = int(round(capture_sr * hop_seconds))
        # Base silence threshold for toddlers (2-4 years): they produce
        # shorter utterances with longer pauses between words.
        # This is dynamically adjusted by EmotionReactor based on detected emotion.
        silence_threshold_seconds = self.emotion_reactor.NORMAL_SILENCE
        max_listen_seconds = self.MAX_LISTEN_SECONDS
        circular_maxlen = vad_circular_maxlen(hop_seconds)
        circular_buffer: deque[np.ndarray] = deque(maxlen=circular_maxlen)
        pre_roll_blocks = vad_pre_roll_blocks(hop_seconds)
        current_segment: list[np.ndarray] = []
        silence_seconds = 0.0
        listen_seconds = 0.0
        speech_active = False
        audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)

        # Wait for camera models to finish loading before loading Whisper
        # to avoid CPU contention from concurrent heavy model initialization.
        if self.camera_ready_event is not None:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: esperando a que la cámara termine de cargar modelos...",
            )
            self.camera_ready_event.wait(timeout=30)

        whisper_model = None
        if not self.cloud_mode:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: cargando Whisper (puede tardar la primera vez)...",
            )
            whisper_model = self._load_whisper_model()
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: Whisper listo" if whisper_model is not None else "AudioWorker: Whisper no disponible",
            )
        else:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: modo NUBE activo — omitiendo carga de Whisper local",
            )
        vad = self._load_vad(stt_rate)

        # LLM al inicio, una vez, antes de abrir el mic. Si carga en segundo
        # plano el primer unknown sale enlatado.
        if not self.cloud_mode and self.fallback_llm is not None:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: cargando LLM de fallback...",
            )
            try:
                self.fallback_llm.load()
                _queue_message_with_semaphore(
                    self.message_queue, self.message_semaphore, "log",
                    "AudioWorker: LLM de fallback listo",
                )
            except Exception as exc:
                _queue_message_with_semaphore(
                    self.message_queue, self.message_semaphore, "log",
                    f"AudioWorker: LLM de fallback no disponible: {exc}",
                )
            try:
                if self.fallback_llm.is_available:
                    _queue_message_with_semaphore(
                        self.message_queue, self.message_semaphore, "log",
                        "AudioWorker: calentando LLM (sin voz)...",
                    )
                    self.fallback_llm.warmup()
                    _queue_message_with_semaphore(
                        self.message_queue, self.message_semaphore, "log",
                        "AudioWorker: LLM caliente",
                    )
            except Exception as exc:
                _queue_message_with_semaphore(
                    self.message_queue, self.message_semaphore, "log",
                    f"AudioWorker: warmup LLM omitido: {exc}",
                )

        self._set_eyes("escuchando")

        _dlog = get_debug_logger()
        if _dlog:
            llm_status = "disponible" if (self.fallback_llm and self.fallback_llm.is_available) else "no disponible"
            _dlog.log_output("AUDIO_INIT", f"AudioWorker modelos cargados (Whisper + VAD + LLM={llm_status})")

        overflow_hits = [0]
        drop_hits = [0]

        if self.microphone_device_index == -1:
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "log",
                "AudioWorker: deshabilitado (sin micrófono). Modo solo visión activo.",
            )
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "status",
                {"mic": "deshabilitado", "volume": 0},
            )
            while not self._stop_event.is_set():
                time.sleep(0.5)
            log_action("AudioWorker", "tarea _run finalizada (sin micrófono)")
            return

        try:
            def listen_until_cut() -> np.ndarray | None:
                nonlocal speech_active, silence_seconds, listen_seconds, current_segment
                drops_seen = 0
                vad_tag = vad_log_label(getattr(vad, "_mode", "energy"))
                while not self._stop_event.is_set():
                    try:
                        audio_block = audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        silence_seconds, drops_seen = apply_capture_drops(
                            speech_active, drop_hits[0], drops_seen, silence_seconds
                        )
                        continue

                    if np.issubdtype(audio_block.dtype, np.integer):
                        audio_block = pcm_s16le_to_float32(audio_block)
                    audio_block = downsample_capture_to_stt(
                        audio_block, capture_sr, stt_rate
                    )
                    duration = stt_block_duration_seconds(
                        int(audio_block.size), stt_rate
                    )

                    circular_buffer.append(audio_block)

                    try:
                        rms = float(np.sqrt(np.mean(audio_block ** 2)))
                        if np.isnan(rms) or np.isinf(rms):
                            volume_pct = 0
                        else:
                            volume_pct = min(100, int(rms * 300))
                    except Exception:
                        volume_pct = 0

                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "status",
                        {"mic": mic_label, "volume": volume_pct},
                    )

                    from session_policy import mic_open_for_listen

                    speaker_on = self.speech_worker is not None and self.speech_worker.is_busy()
                    if not mic_open_for_listen(speaker_on, time.monotonic(), self._echo_mute_until):
                        if speech_active:
                            speech_active = False
                            silence_seconds = 0.0
                            listen_seconds = 0.0
                            current_segment = []
                            circular_buffer.clear()
                            if hasattr(vad, "reset"):
                                vad.reset()
                        continue

                    speech_detected = vad.has_speech(audio_block)

                    emotion_context = getattr(self.intent_dispatcher, "current_emotion", None)
                    silence_threshold_seconds = self.emotion_reactor.get_silence_threshold(emotion_context)

                    if speech_detected:
                        if not speech_active:
                            speech_active = True
                            listen_seconds = 0.0
                            buf_list = list(circular_buffer)
                            pre_roll = buf_list[:-1][-pre_roll_blocks:] if len(buf_list) > 1 else []
                            current_segment = pre_roll + [audio_block]
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "log",
                                f"{vad_tag}: escuchando... (umbral silencio: {silence_threshold_seconds:.1f}s, máx {max_listen_seconds:.0f}s)",
                            )
                        else:
                            current_segment.append(audio_block)
                        silence_seconds = 0.0
                    elif speech_active:
                        current_segment.append(audio_block)
                        silence_seconds += duration

                    silence_seconds, drops_seen = apply_capture_drops(
                        speech_active, drop_hits[0], drops_seen, silence_seconds
                    )

                    if speech_active:
                        listen_seconds += duration
                        silenced = silence_seconds >= silence_threshold_seconds
                        timed_out = listen_seconds >= max_listen_seconds
                        if silenced or timed_out:
                            reason = (
                                "silencio detectado"
                                if silenced
                                else f"tiempo máximo ({max_listen_seconds:.0f}s)"
                            )
                            segment_audio = np.concatenate(current_segment, axis=0) if current_segment else np.array([], dtype=np.float32)
                            seg_s = len(segment_audio) / 16000.0
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "log",
                                f"{vad_tag}: {reason}, cortando audio ({seg_s:.1f}s)",
                            )
                            log_action(
                                "AudioWorker",
                                f"corte de escucha: {reason} (capturado {listen_seconds:.1f}s, wav {seg_s:.1f}s)",
                            )
                            speech_active = False
                            silence_seconds = 0.0
                            listen_seconds = 0.0
                            current_segment = []
                            circular_buffer.clear()
                            if hasattr(vad, "reset"):
                                vad.reset()
                            return segment_audio
                return None

            echo_until = [self._echo_mute_until]

            def _speaker_busy() -> bool:
                return self.speech_worker is not None and self.speech_worker.is_busy()

            def _sync_echo_until() -> None:
                echo_until[0] = self._echo_mute_until

            use_alsa = sys.platform.startswith("linux")
            capture = None
            input_stream = None
            if capture_sr != stt_rate:
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"AudioWorker: mic {capture_sr} Hz → STT {stt_rate} Hz (fuera del callback)",
                )
            mic_label = f"{self.microphone_device_index} activo"

            if use_alsa:
                from alsa_capture import (
                    AlsaCapture,
                    ENV_ALSA_CAPTURE_DEVICE,
                    read_arecord_list,
                    resolve_alsa_capture_device,
                )

                sd_name = ""
                try:
                    info = sd.query_devices(self.microphone_device_index)
                    sd_name = str(info.get("name") or "")
                except Exception:
                    sd_name = ""
                device = resolve_alsa_capture_device(
                    env=os.environ,
                    arecord_l=read_arecord_list(),
                    sounddevice_name=sd_name,
                )
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"AudioWorker: arecord {device} 48k S16_LE (env {ENV_ALSA_CAPTURE_DEVICE} override si está)",
                )
                capture = AlsaCapture(
                    device=device,
                    audio_queue=audio_queue,
                    drop_hits=drop_hits,
                    stop_event=self._stop_event,
                    enqueue=enqueue_mic_block,
                    speaker_busy=_speaker_busy,
                    echo_until=echo_until,
                )
                self._alsa_capture = capture
                capture.start()
                if capture.pipe_size:
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"AudioWorker: pipe_size={capture.pipe_size}",
                    )
                if capture.negotiated:
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"AudioWorker: ALSA negociado {capture.negotiated}",
                    )
            else:

                def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
                    if status:
                        overflow_hits[0] += 1
                    if capture_muted[0] or _speaker_busy() or time.monotonic() < echo_until[0]:
                        return
                    audio_block = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
                    enqueue_mic_block(audio_queue, audio_block, drop_hits)

                capture_muted = [False]
                input_stream = sd.InputStream(
                    device=self.microphone_device_index,
                    channels=1,
                    samplerate=capture_sr,
                    blocksize=block_size,
                    dtype="float32",
                    callback=callback,
                )
                self._input_stream = input_stream
                input_stream.start()

            try:
                while not self._stop_event.is_set():
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "status",
                        {"mic": mic_label, "volume": 0},
                    )
                    vad_tag = vad_log_label(getattr(vad, "_mode", "energy"))
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        f"{vad_tag}: escuchando...",
                    )
                    overflow_hits[0] = 0
                    drop_hits[0] = 0
                    overrun_before = capture.overrun_hits if capture is not None else 0
                    restart_before = capture.restarts if capture is not None else 0
                    busy_before = capture.busy_hits if capture is not None else 0
                    if capture is not None:
                        capture.set_muted(False)
                    else:
                        capture_muted[0] = False
                    _sync_echo_until()
                    segment = listen_until_cut()
                    if capture is not None:
                        n_xrun = capture.overrun_hits - overrun_before
                        n_drop = drop_hits[0]
                        n_restart = capture.restarts - restart_before
                        n_busy = capture.busy_hits - busy_before
                    else:
                        n_xrun = overflow_hits[0]
                        n_drop = drop_hits[0]
                        n_restart = 0
                        n_busy = 0
                    overflow_hits[0] = 0
                    drop_hits[0] = 0
                    if n_xrun:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: {n_xrun} overruns/xruns ALSA (captura sigue viva)",
                        )
                        log_action("AudioWorker", f"{n_xrun} overruns/xruns ALSA")
                    if n_drop:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: {n_drop} bloques descartados (cola llena)",
                        )
                        log_action("AudioWorker", f"{n_drop} bloques descartados (cola llena)")
                    if n_restart:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: arecord reiniciado {n_restart} veces",
                        )
                    if n_busy:
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            "AudioWorker: hw: busy (ver LATENCIA PipeWire; lsof /dev/snd/pcmC*D0c)",
                        )
                    if capture is not None:
                        capture.set_muted(True)
                    else:
                        capture_muted[0] = True
                    self._drain_audio_queue(audio_queue)
                    if self._stop_event.is_set():
                        break
                    if segment is not None and segment.size:
                        self._handle_segment(segment, whisper_model, audio_queue)
                    _sync_echo_until()
            finally:
                if capture is not None:
                    capture.stop()
                    self._alsa_capture = None
                if input_stream is not None:
                    try:
                        input_stream.stop()
                    except Exception:
                        pass
                    try:
                        input_stream.close()
                    except Exception:
                        pass
                    self._input_stream = None

        except Exception as exc:
            log_action("AudioWorker", f"ERROR: {exc}")
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en micrófono: {exc}")
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "status",
                {"mic": "error"},
            )
        finally:
            log_action("AudioWorker", "tarea _run finalizada")

    @staticmethod
    def _drain_audio_queue(audio_queue: queue.Queue) -> None:
        while True:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                break

    def _silence_mic_after_speaker(self, audio_queue: queue.Queue) -> None:
        from session_policy import ECHO_MUTE_SECONDS

        self._drain_audio_queue(audio_queue)
        self._echo_mute_until = time.monotonic() + ECHO_MUTE_SECONDS

    def _sync_playtime_limit(self) -> None:
        state = self._robot_state
        if state is None:
            return
        limit = int(getattr(state, "playtime_limit_minutes", 0) or 0)
        self.playtime_guard.limit_minutes = limit

    def _handle_segment(self, audio_segment: np.ndarray, whisper_model: Any, audio_queue: queue.Queue) -> None:
        if audio_segment.size == 0:
            return

        _dlog = get_debug_logger()
        segment_start = time.monotonic()
        segment_duration_s = len(audio_segment) / 16000.0
        if _dlog:
            _dlog.log_input("SEGMENT", f"Audio segment ({segment_duration_s:.1f}s, {len(audio_segment)} samples)")

        try:
            # 1. Transcribe (cloud o local según modo)
            _t_transcribe = time.monotonic()
            low_confidence = False
            avg_logprob: float | None = None
            no_speech_prob: float | None = None
            if self.cloud_mode and self.cloud_stt is not None:
                if _dlog:
                    _dlog.log_input("TRANSCRIPTION", f"Audio ({segment_duration_s:.1f}s) [CLOUD]")
                raw_text = self.cloud_stt.transcribe(audio_segment)
                save_named_transcript_wav(audio_segment, raw_text, sample_rate=16000)
            else:
                if _dlog:
                    _dlog.log_input("TRANSCRIPTION", f"Audio ({segment_duration_s:.1f}s) [LOCAL]")
                transcription = self._transcribe(whisper_model, audio_segment)
                raw_text = transcription.text
                low_confidence = transcription.low_confidence
                avg_logprob = transcription.avg_logprob
                no_speech_prob = transcription.no_speech_prob
            if _dlog:
                conf_bits = []
                if avg_logprob is not None:
                    conf_bits.append(f"avg_logprob={avg_logprob:.3f}")
                if no_speech_prob is not None:
                    conf_bits.append(f"no_speech={no_speech_prob:.3f}")
                if low_confidence:
                    conf_bits.append("LOW_CONFIDENCE")
                extra = f" ({', '.join(conf_bits)})" if conf_bits else ""
                _dlog.log_output("TRANSCRIPTION", f"\"{raw_text}\"{extra}", elapsed_ms=(time.monotonic() - _t_transcribe) * 1000)

            whisper_raw = raw_text
            extra_words: tuple[str, ...] = ()
            if (
                self.game_engine is not None
                and self.game_engine.is_active
                and self.game_engine.game_type == "piedra_papel_tijera"
            ):
                extra_words = ("piedra", "papel", "tijera")
            checker = spanish_vocab_checker(getattr(self.intent_dispatcher, "nlp", None))
            raw_text = polish_stt_text(
                raw_text,
                extra_words=extra_words,
                is_known_spanish=checker,
            )
            if raw_text != whisper_raw:
                log_action("STT", f'crudo="{whisper_raw}" filtrado="{raw_text}"')
                if _dlog:
                    _dlog.log_output("STT_FILTER", f'"{whisper_raw}" → "{raw_text}"')
            elif raw_text.strip():
                log_action("STT", f'"{raw_text}"')

            elapsed_stt_ms = (time.monotonic() - _t_transcribe) * 1000
            if low_confidence:
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"[STT] Baja confianza ({elapsed_stt_ms:.0f}ms)"
                    f"{f' avg_logprob={avg_logprob:.3f}' if avg_logprob is not None else ''}"
                    f' text="{raw_text}"',
                )
                if segment_duration_s > 1.5 and self.speech_worker is not None:
                    self.speech_worker.speak_and_wait("No te escuché bien, ¿me lo decís de nuevo?")
                    self._silence_mic_after_speaker(audio_queue)
                return
            if raw_text.strip():
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f"[STT] Transcrito ({elapsed_stt_ms:.0f}ms): \"{raw_text}\"",
                )
            else:
                from whisper_process import stt_empty_log

                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    stt_empty_log(
                        whisper_available=whisper_model is not None,
                        elapsed_ms=elapsed_stt_ms,
                    ),
                )
                return

            from session_policy import is_clear_keyword_intent, utterance_too_thin

            if utterance_too_thin(raw_text) and not is_clear_keyword_intent(raw_text):
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "log",
                    f'[STT] Muy corto para una respuesta: "{raw_text}"',
                )
                if segment_duration_s > 0.8 and self.speech_worker is not None:
                    self.speech_worker.speak_and_wait(
                        "No te escuché bien, ¿me lo decís de nuevo?",
                    )
                    self._silence_mic_after_speaker(audio_queue)
                return

            # 2. Sanitize (PII removal)
            _t_sanitize = time.monotonic()
            if _dlog:
                _dlog.log_input("SANITIZATION", f"text=\"{raw_text}\"")
            sanitized_payload = self.sanitizer.sanitize(raw_text)
            sanitized_text = sanitized_payload.get("sanitized_text", "")
            if _dlog:
                _dlog.log_output("SANITIZATION", f"\"{sanitized_text}\"", elapsed_ms=(time.monotonic() - _t_sanitize) * 1000)

            # 3. Vocabulary tracking (#EPIC-003 — linguistic development)
            new_words: list[str] = []
            if self.vocabulary_tracker is not None and sanitized_text:
                try:
                    new_words = self.vocabulary_tracker.process_transcript(sanitized_text)
                    if new_words:
                        _queue_message_with_semaphore(
                            self.message_queue, self.message_semaphore, "log",
                            f"Vocabulario: {len(new_words)} palabras nuevas detectadas: {', '.join(new_words[:5])}",
                        )
                    hours_prior = None
                    if new_words:
                        hours_prior = self.vocabulary_tracker.hours_since_prior_discovery(
                            excluding_last_n=len(new_words),
                        )
                    vocab_msg = self._vocab_alerter.consider(new_words, hours_prior)
                    if vocab_msg:
                        self._notify_vocab_parent(vocab_msg)
                except Exception:
                    pass
            else:
                self._flush_vocab_parent_alert()

            # 4. Emotion context
            emotion_context = getattr(self.intent_dispatcher, "current_emotion", None)

            # 5. Intent dispatch (NLU via spaCy semantic similarity)
            _t_intent = time.monotonic()
            if _dlog:
                _dlog.log_input("NLU", f"text=\"{sanitized_text}\", emotion={emotion_context}")
            from session_policy import (
                game_keyword_while_muted,
                is_clear_keyword_intent,
                should_run_intent_dispatcher,
            )

            began_muted = self.intent_mute.is_muted
            keyword_now = is_clear_keyword_intent(sanitized_text)
            game_kw = game_keyword_while_muted(began_muted, keyword_now)
            if game_kw:
                self.intent_mute.note_game_keyword(sanitized_text)
                intent_payload = {
                    "intent_name": game_kw,
                    "confidence": 0.95,
                    "response": "",
                    "pilar": "cognitivo",
                }
            elif should_run_intent_dispatcher(self.intent_mute.is_muted):
                intent_payload = self.intent_dispatcher.dispatch(sanitized_text, emotion=emotion_context)
            else:
                intent_payload = {
                    "intent_name": "unknown",
                    "confidence": 0.0,
                    "response": "",
                    "pilar": "general",
                }
            if _dlog:
                _dlog.log_output(
                    "NLU",
                    f"intent={intent_payload.get('intent_name', '?')} conf={intent_payload.get('confidence', 0):.3f}"
                    f"{' muted' if began_muted else ''}",
                    elapsed_ms=(time.monotonic() - _t_intent) * 1000,
                )

            # 6. Emotion reactor — crisis detection (#EPIC-005 CA#1)
            awaiting_llm = began_muted and not game_kw
            _t_reactor = time.monotonic()
            if _dlog:
                _dlog.log_input("EMOTION_REACTOR", f"emotion={emotion_context}, intent={intent_payload.get('intent_name')}")
            if not awaiting_llm:
                intent_payload = self.emotion_reactor.evaluate(emotion_context, intent_payload)
            is_crisis = intent_payload.get("is_crisis", False)
            if _dlog:
                _dlog.log_output("EMOTION_REACTOR", f"is_crisis={is_crisis}", elapsed_ms=(time.monotonic() - _t_reactor) * 1000)

            from session_policy import (
                NIGHT_DECLINE_PHRASE,
                PLAYTIME_DECLINE_PHRASE,
                night_should_engage,
            )

            self._sync_playtime_limit()
            night_on = bool(getattr(self._robot_state, "night_mode", False)) if self._robot_state else False
            intent_name = str(intent_payload.get("intent_name", ""))
            gated = False
            if awaiting_llm:
                gated = False
            elif night_on and not night_should_engage(intent_name):
                intent_payload = {
                    "intent_name": "night_rest",
                    "confidence": 1.0,
                    "response": NIGHT_DECLINE_PHRASE,
                    "pilar": "emocional",
                }
                gated = True
            elif not self.playtime_guard.allows_intent(intent_name):
                intent_payload = {
                    "intent_name": "playtime_rest",
                    "confidence": 1.0,
                    "response": PLAYTIME_DECLINE_PHRASE,
                    "pilar": "emocional",
                }
                gated = True

            # 7. Game / yoga / cuento — multi-turno
            if not gated:
                if self.game_engine is not None:
                    intent_payload = self.game_engine.process_or_passthrough(sanitized_text, intent_payload)
                if self.yoga_engine is not None:
                    intent_payload = self.yoga_engine.process_or_passthrough(sanitized_text, intent_payload)
                if self.story_engine is not None:
                    if self.story_engine.is_waiting_for_child:
                        self._invalidate_story_timer()
                    intent_payload = self.story_engine.process_or_passthrough(sanitized_text, intent_payload)

            # 8. Routine acknowledgment (#EPIC-007)
            intent_name = intent_payload.get("intent_name", "")
            if intent_name == "routine_ack" and self.routine_scheduler is not None:
                try:
                    ack_msg = self.routine_scheduler.acknowledge_routine("any")
                    if ack_msg:
                        intent_payload["response"] = ack_msg
                except Exception:
                    pass

            if intent_name == "stop_music_request" and self.speech_worker is not None:
                self.stop_story_from_api()
                self.speech_worker.stop_music()

            if intent_name == "hug_request":
                if self.companion is not None:
                    try:
                        self.companion.hug()
                    except Exception:
                        pass
                if self.eye_display is not None and hasattr(self.eye_display, "set_pictogram"):
                    try:
                        self.eye_display.set_pictogram("abrazo")
                    except Exception:
                        pass

            # 8.5. Fallback LLM — generate empathetic response for unknown intents
            intent_name = intent_payload.get("intent_name", "")
            game_active = self.game_engine is not None and self.game_engine.is_active
            story_active = self.story_engine is not None and self.story_engine.is_active
            yoga_active = self.yoga_engine is not None and self.yoga_engine.is_active
            story_reflect = intent_payload.get("intent_name") == "story_reflect_answer"
            from session_policy import should_allow_llm, stt_looks_like_garbage

            allow_llm = should_allow_llm(
                intent_name,
                game_active=game_active,
                story_active=story_active,
                yoga_active=yoga_active,
                gated=gated,
                story_reflect=story_reflect,
                garbage_stt=stt_looks_like_garbage(sanitized_text),
            )
            llm_history = self.conversation_memory.messages()
            will_llm = allow_llm and (
                (self.cloud_mode and self.cloud_llm is not None and self.cloud_llm.is_available)
                or (
                    not self.cloud_mode
                    and self.fallback_llm is not None
                    and self.fallback_llm.is_available
                )
            )
            if will_llm:
                self._thinking_eyes(True)
            try:
                if allow_llm and self.cloud_mode and self.cloud_llm is not None and self.cloud_llm.is_available:
                    _t_llm = time.monotonic()
                    if _dlog:
                        _dlog.log_input("LLM_FALLBACK", f'text="{sanitized_text}" [CLOUD]')
                    if story_reflect:
                        title = intent_payload.get("story_title") or "el cuento"
                        digest = intent_payload.get("story_digest") or ""
                        prompt = (
                            f"Leímos '{title}'. Recorte: {digest}. "
                            f"El nene dijo: {sanitized_text}. "
                            "Comentá en una frase corta. No narres el cuento."
                        )
                        llm_response = self.cloud_llm.generate(prompt, emotion_context, history=llm_history)
                    else:
                        llm_response = self.cloud_llm.generate(sanitized_text, emotion_context, history=llm_history)
                    if llm_response:
                        if story_reflect:
                            intent_payload["intent_name"] = "story_reflect_answer"
                            intent_payload["pilar"] = "cognitivo"
                        elif intent_name == "unknown":
                            intent_payload["intent_name"] = "llm_fallback"
                            intent_payload["pilar"] = "general"
                        intent_payload["response"] = llm_response
                    if _dlog:
                        _dlog.log_output(
                            "LLM_FALLBACK",
                            f'response="{llm_response}"' if llm_response else "sin respuesta",
                            elapsed_ms=(time.monotonic() - _t_llm) * 1000,
                        )
                elif allow_llm and self.fallback_llm is not None and self.fallback_llm.is_available:
                    _t_llm = time.monotonic()
                    _queue_message_with_semaphore(
                        self.message_queue,
                        self.message_semaphore,
                        "log",
                        "AudioWorker: pensando la respuesta...",
                    )
                    if _dlog:
                        _dlog.log_input("LLM_FALLBACK", f"text=\"{sanitized_text}\"")
                    if story_reflect:
                        title = intent_payload.get("story_title") or "el cuento"
                        digest = intent_payload.get("story_digest") or ""
                        prompt = (
                            f"Leímos '{title}'. Recorte: {digest}. "
                            f"El nene dijo: {sanitized_text}. "
                            "Comentá en una frase corta. No narres el cuento."
                        )
                        llm_response = self.fallback_llm.generate(prompt, emotion_context, history=llm_history)
                    else:
                        llm_response = self.fallback_llm.generate(sanitized_text, emotion_context, history=llm_history)
                    if llm_response:
                        if story_reflect:
                            intent_payload["intent_name"] = "story_reflect_answer"
                            intent_payload["pilar"] = "cognitivo"
                        elif intent_name == "unknown":
                            intent_payload["intent_name"] = "llm_fallback"
                            intent_payload["pilar"] = "general"
                        intent_payload["response"] = llm_response
                    else:
                        why = getattr(self.fallback_llm, "last_fail", "") or "vacío"
                        _queue_message_with_semaphore(
                            self.message_queue,
                            self.message_semaphore,
                            "log",
                            f"AudioWorker: LLM no respondió ({why})",
                        )
                    if _dlog:
                        _dlog.log_output(
                            "LLM_FALLBACK",
                            f"response=\"{llm_response}\"" if llm_response else "sin respuesta",
                            elapsed_ms=(time.monotonic() - _t_llm) * 1000,
                        )
            finally:
                if will_llm:
                    self._thinking_eyes(False)

            if intent_name == "unknown" and not str(intent_payload.get("response", "")).strip():
                # Último recurso si el LLM no contestó. No es un intent matcheado.
                intent_payload["response"] = self.intent_dispatcher._pick_response(
                    "unknown_fallback",
                    [
                        "¿Querés jugar al veo veo, escuchar música, un cuento o charlar un rato?",
                        "Contame un poco más, te escucho.",
                        "No te seguí del todo. ¿Me lo decís de otra forma?",
                        "¿Seguimos charlando o preferís un juego?",
                    ],
                )
                intent_payload["pilar"] = "general"

            # 8.6 Music playback for song_request
            if intent_name == "song_request":
                music_dir = Path(__file__).resolve().parent / "music"
                music_files = []
                if music_dir.exists():
                    allowed_ext = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
                    music_files = [f for f in sorted(music_dir.iterdir()) if f.suffix.lower() in allowed_ext]

                if music_files:
                    import random
                    chosen_song = random.choice(music_files)
                    song_title = chosen_song.stem.replace("_", " ")
                    intent_payload["response"] = f"¡Me encanta cantar! Vamos a escuchar {song_title}."
                    intent_payload["play_music_file"] = str(chosen_song)
                else:
                    intent_payload["response"] = "Todavía no tenés canciones guardadas. ¡Pedile a mamá o papá que te suban una desde el celular!"

            # 8.7 Parse and execute LLM action tags (#LLM-SKILLS)
            response_text_raw = str(intent_payload.get("response", ""))
            actions, clean_response = self._parse_action_tags(response_text_raw)
            if actions:
                self._execute_actions(actions, intent_payload, user_text=sanitized_text)
                if _dlog:
                    _dlog.log_output("LLM_ACTIONS", f"actions={[a['action'] for a in actions]}")
            if not clean_response and any(a["action"] == "NOTIFY_PARENT" for a in actions):
                clean_response = "Listo, le aviso a mamá o papá."
            intent_payload["response"] = clean_response

            if began_muted and self.intent_mute.is_muted:
                self.intent_mute.note_child_turn_still_muted(sanitized_text)

            # 9. Determine pilar for telemetry
            pilar = intent_payload.get("pilar", "general")

            # 10. Send transcript message to UI
            _queue_critical_message(
                self.message_queue,
                self.message_semaphore,
                "transcript",
                {
                    "raw_text": raw_text,
                    "sanitized": sanitized_payload,
                    "emotion": emotion_context,
                    "intent": intent_payload,
                    "new_words": new_words,
                },
            )

            # 11. Telemetry logging (#EPIC-004)
            duration_s = time.monotonic() - segment_start
            self.playtime_guard.add_seconds(duration_s)
            if self.telemetry is not None:
                try:
                    self.telemetry.log_interaction(
                        pilar=pilar,
                        intent_name=intent_name,
                        emotion=emotion_context.get("label") if emotion_context else None,
                        emotion_score=float(emotion_context.get("score", 0.0)) if emotion_context else 0.0,
                        duration_s=duration_s,
                    )
                    if is_crisis and emotion_context:
                        self.telemetry.log_crisis_event(
                            emotion=emotion_context.get("label", "unknown"),
                            emotion_score=float(emotion_context.get("score", 0.0)),
                            response=intent_payload.get("response", ""),
                        )
                        # Auto-notify parent on crisis (#LLM-SKILLS)
                        if self._robot_state is not None:
                            self._robot_state.push_notification(
                                "crisis",
                                f"Crisis emocional detectada: {emotion_context.get('label', 'desconocida')} "
                                f"(intensidad: {emotion_context.get('score', 0):.0%})",
                                extra={
                                    "emotion": emotion_context.get("label"),
                                    "score": float(emotion_context.get("score", 0.0)),
                                },
                            )
                    if new_words and self.vocabulary_tracker is not None:
                        stats = self.vocabulary_tracker.get_stats()
                        self.telemetry.log_vocabulary_update(
                            new_words=new_words,
                            total_words=stats.get("total_words", 0),
                        )
                except Exception:
                    pass

            # 11.5 Auto-notify parent for call_parent intent (#LLM-SKILLS)
            if intent_name == "call_parent" and self._robot_state is not None:
                self._robot_state.push_notification(
                    "pedido",
                    "El nene está pidiendo hablar con mamá o papá.",
                    extra={"intent": "call_parent"},
                )

            # 12. TTS — speak the response and block until playback finishes.
            response_text = self._strip_unspeakable(str(intent_payload.get("response", "")))
            intent_payload["response"] = response_text
            skip_cut = bool(intent_payload.get("skip_tts_truncate"))
            story_chunk = intent_payload.get("story_chunk")
            if not skip_cut and not story_chunk and not intent_payload.get("story_need_reflection") and intent_payload.get("intent_name") != "story_reflect_answer":
                # Truncar respuestas largas a ~25 palabras para mantener TTS < 4s.
                response_text = self._truncate_response(response_text, max_words=25)
            if self.speech_worker is not None:
                _t_tts = time.monotonic()
                if story_chunk or intent_payload.get("story_need_reflection") or intent_payload.get("intent_name") == "story_reflect_answer":
                    if _dlog:
                        _dlog.log_input("TTS", "cuento turno")
                    self._speak_story_payload(intent_payload, generation=None)
                elif response_text:
                    if _dlog:
                        _dlog.log_input("TTS", f"text=\"{response_text}\"")
                    self.speech_worker.speak_and_wait(response_text, timeout=60.0)
                self._silence_mic_after_speaker(audio_queue)
                if _dlog:
                    _dlog.log_output("TTS", "Reproducción completada", elapsed_ms=(time.monotonic() - _t_tts) * 1000)

            self._remember_turn(sanitized_text, intent_payload, response_text)

            # Reproducir archivo de música si fue solicitado
            music_to_play = intent_payload.get("play_music_file")
            if music_to_play and self.speech_worker is not None:
                self.stop_story_from_api()
                self.speech_worker.play_audio_file(music_to_play)
                self._silence_mic_after_speaker(audio_queue)

            if _dlog:
                _dlog.log_output("SEGMENT", "Pipeline completo", elapsed_ms=(time.monotonic() - segment_start) * 1000)

        except Exception as exc:
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en transcripción o NLU: {exc}")
        finally:
            # Flush stale audio accumulated during processing + playback
            while True:
                try:
                    audio_queue.get_nowait()
                except queue.Empty:
                    break

    @staticmethod
    def _truncate_response(text: str, max_words: int = 25) -> str:
        """Trunca respuestas TTS largas para mantener latencia baja.

        Corta en el último límite de oración dentro de *max_words* para
        evitar cortes abruptos.  Si no encuentra un punto natural, corta
        por palabras y agrega puntos suspensivos.
        """
        words = text.split()
        if len(words) <= max_words:
            return text

        truncated = " ".join(words[:max_words])
        # Intentar cortar en el último punto/signo de interrogación/exclamación
        for sep in (".", "?", "!", "。"):
            last_idx = truncated.rfind(sep)
            if last_idx > 0:
                return truncated[: last_idx + 1]
        # Sin límite de oración encontrado — cortar y agregar puntos suspensivos
        return truncated.rstrip(",;: ") + "."

    # ------------------------------------------------------------------
    # LLM Action Tags — Parser & Executor (#LLM-SKILLS)
    # ------------------------------------------------------------------

    # Regex to match action tags like [PLAY_MUSIC], [EXPRESSION:feliz],
    # [NOTIFY_PARENT:razón del aviso], etc.
    _ACTION_TAG_RE = re.compile(
        r"\["
        r"(PLAY_MUSIC|STOP_MUSIC|NOTIFY_PARENT|EXPRESSION|CELEBRATE|CALM_MODE|INTENTS_OFF|INTENTS_ON)"
        r"(?::([^\]]*))?"
        r"\]",
        re.IGNORECASE,
    )
    _ANY_BRACKET_RE = re.compile(r"\[[^\]]*\]")
    _BARE_NOTIFY_RE = re.compile(r"NOTIFY_PARENT\s*:?\s*.*$", re.IGNORECASE)
    _MUSIC_REQUEST_RE = re.compile(
        r"canci[oó]n|m[uú]sica|cantame|canta\b|reproduc|bail(ar|e)|pon[ée]\s+(una\s+)?(canci|m[uú]sica)",
        re.IGNORECASE,
    )

    def _parse_action_tags(self, text: str) -> tuple[list[dict[str, str]], str]:
        """Extrae action tags del texto de respuesta de la LLM.

        Returns:
            Tupla (lista de acciones, texto limpio sin tags).
            Cada acción es un dict {"action": "PLAY_MUSIC", "param": "..."}.
        """
        actions: list[dict[str, str]] = []
        for match in self._ACTION_TAG_RE.finditer(text):
            action_name = match.group(1).upper()
            param = (match.group(2) or "").strip()
            actions.append({"action": action_name, "param": param})

        clean_text = self._strip_unspeakable(text)
        return actions, clean_text

    def _strip_unspeakable(self, text: str) -> str:
        """Saca tags, corchetes y NOTIFY_PARENT suelto para que el TTS no los lea."""
        cleaned = self._ACTION_TAG_RE.sub("", text or "")
        cleaned = self._ANY_BRACKET_RE.sub("", cleaned)
        cleaned = self._BARE_NOTIFY_RE.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def _user_asked_for_music(self, user_text: str) -> bool:
        return bool(self._MUSIC_REQUEST_RE.search(user_text or ""))

    def _execute_actions(
        self,
        actions: list[dict[str, str]],
        intent_payload: dict,
        user_text: str = "",
    ) -> None:
        """Ejecuta las acciones parseadas de los tags de la LLM.

        Cada acción interactúa con un subsistema del robot:
        - PLAY_MUSIC: reproduce música de la carpeta music/
        - STOP_MUSIC: detiene la música en curso
        - NOTIFY_PARENT: encola notificación para la app Android
        - EXPRESSION: cambia la expresión de los ojos
        - CELEBRATE: celebración visual + notifica al padre
        - CALM_MODE: baja volumen y expresión tranquila
        """
        _dlog = get_debug_logger()
        from session_policy import apply_llm_intent_actions

        apply_llm_intent_actions(self.intent_mute, actions, user_text)

        for action_info in actions:
            action = action_info["action"]
            param = action_info["param"]

            try:
                if action == "PLAY_MUSIC":
                    intent_name_now = str(intent_payload.get("intent_name", ""))
                    if intent_name_now != "song_request" and not self._user_asked_for_music(user_text):
                        if _dlog:
                            _dlog.log_output(
                                "ACTION",
                                "PLAY_MUSIC ignorado: el nene no pidió música",
                            )
                        continue
                    # Reproducir una canción al azar de music/
                    music_dir = Path(__file__).resolve().parent / "music"
                    if music_dir.exists():
                        import random
                        allowed_ext = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
                        music_files = [f for f in sorted(music_dir.iterdir()) if f.suffix.lower() in allowed_ext]
                        if music_files:
                            chosen = random.choice(music_files)
                            intent_payload["play_music_file"] = str(chosen)
                            if _dlog:
                                _dlog.log_output("ACTION", f"PLAY_MUSIC -> {chosen.name}")

                elif action == "STOP_MUSIC":
                    if self.speech_worker is not None:
                        self.speech_worker.stop_music()
                        if _dlog:
                            _dlog.log_output("ACTION", "STOP_MUSIC ejecutado")

                elif action == "NOTIFY_PARENT":
                    reason = param or "TEO quiere avisar algo"
                    if self._robot_state is not None:
                        self._robot_state.push_notification(
                            "aviso",
                            reason,
                        )
                        if _dlog:
                            _dlog.log_output("ACTION", f"NOTIFY_PARENT -> {reason}")

                elif action == "EXPRESSION":
                    valid_expressions = {"feliz", "triste", "sorprendido", "enojado", "neutral"}
                    expr = param.lower() if param else "neutral"
                    if expr in valid_expressions and self.eye_display is not None:
                        self.eye_display.set_expression(expr)
                        if _dlog:
                            _dlog.log_output("ACTION", f"EXPRESSION -> {expr}")

                elif action == "CELEBRATE":
                    # Expresión feliz + notificar padre del logro (qué hizo)
                    if self.eye_display is not None:
                        self.eye_display.set_expression("feliz")
                    from parent_alerts import describe_child_achievement
                    achievement = describe_child_achievement(
                        param,
                        user_text,
                        str(intent_payload.get("intent_name", "")),
                    )
                    if self._robot_state is not None:
                        self._robot_state.push_notification(
                            "logro",
                            achievement,
                            extra={"detail": param},
                        )
                    if _dlog:
                        _dlog.log_output("ACTION", f"CELEBRATE -> {achievement}")

                elif action in {"INTENTS_OFF", "INTENTS_ON"}:
                    if _dlog:
                        _dlog.log_output("ACTION", f"{action} (mute={self.intent_mute.is_muted})")

                elif action == "CALM_MODE":
                    # Expresión tranquila
                    if self.eye_display is not None:
                        self.eye_display.set_expression("neutral")
                    if _dlog:
                        _dlog.log_output("ACTION", "CALM_MODE ejecutado")

            except Exception as exc:
                if _dlog:
                    _dlog.log_output("ACTION", f"ERROR en {action}: {exc}")

    # Contextual prompt that primes Whisper for Argentine Spanish.
    # Neutral prompt — avoids biasing towards toddler vocabulary which caused
    # hallucinations (e.g. injecting "mamá" into adult speech).  Uses common
    # Argentine expressions to condition the decoder for rioplatense accent.
    _WHISPER_INITIAL_PROMPT: str = (
        "Hola. ¿Cómo estás? Quiero jugar a piedra, papel o tijera. "
        "Sí, dale. No quiero. Juguemos. Contame un cuento."
    )

    def _load_whisper_model(self):
        preferred = (os.environ.get("WHISPER_MODEL") or "medium").strip() or "medium"
        _dlog = get_debug_logger()
        if _dlog:
            _dlog.log_input("WHISPER", f"Cargando modelo {preferred} (proceso hijo)...")
        _t0 = time.monotonic()

        def _log(text: str) -> None:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log", f"AudioWorker: {text}"
            )

        try:
            from vosk_stt import start_vosk
            from whisper_process import (
                default_compute_type,
                load_faster_whisper,
                page_size_hint,
                start_whisper_process,
                whisper_model_candidates,
            )

            hint = page_size_hint()
            if hint:
                _log(hint)

            compute = default_compute_type()
            model = None
            machine = platform.machine().lower()
            sizes = whisper_model_candidates(preferred)
            if machine in ("aarch64", "arm64"):
                sizes = sizes[:1]
            last_bus = False
            for size in sizes:
                if size != preferred:
                    _log(f"Reintento Whisper con modelo={size}")
                model = start_whisper_process(
                    size,
                    compute_type=compute,
                    log=_log,
                )
                if model is not None:
                    if size != preferred:
                        _log(f"Whisper usando {size} (el pedido {preferred} no cargó)")
                    break
                last_bus = True
            if model is None:
                if last_bus:
                    _log("El hijo no cargó; pruebo Whisper en este proceso.")
                try:
                    model = load_faster_whisper(
                        preferred,
                        compute_type=compute,
                        log=_log,
                    )
                except Exception as exc:
                    _log(f"Whisper en proceso falló: {exc}")
                    model = None
            if model is None:
                model = start_vosk(log=_log)
            if _dlog:
                _dlog.log_output(
                    "WHISPER",
                    "Modelo listo" if model is not None else "Whisper no disponible",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return model
        except Exception as exc:
            _log(f"Whisper no se pudo iniciar: {exc}")
            if _dlog:
                _dlog.log_output("WHISPER", f"ERROR: {exc}")
            return None

    @staticmethod
    def _normalize_audio(audio: np.ndarray) -> np.ndarray:
        """Normalize audio volume so soft child voices get amplified to a
        consistent level before transcription.  Avoids clipping."""
        peak = np.max(np.abs(audio))
        if peak < 1e-6:
            return audio  # silence — nothing to normalize
        # Target peak at 0.9 to leave headroom
        return (audio * (0.9 / peak)).astype(np.float32)

    @staticmethod
    def _pre_emphasis(audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
        """Apply pre-emphasis filter to boost high-frequency consonant sounds.

        Speech consonants (t, d, s, l, n, etc.) carry critical information in
        high frequencies (2-8 kHz) that microphones often under-represent.
        Pre-emphasis amplifies these frequencies relative to low-frequency vowel
        energy, helping Whisper distinguish similar-sounding words like
        'lindo' vs 'viendo' or 'soleado' vs 'soñado'.

        y[n] = x[n] - coeff * x[n-1]
        coeff=0.97 is the standard value used in classic ASR systems.
        """
        if len(audio) < 2:
            return audio
        emphasized = np.empty_like(audio)
        emphasized[0] = audio[0]
        emphasized[1:] = audio[1:] - coeff * audio[:-1]
        return emphasized.astype(np.float32)

    @staticmethod
    def _estimate_noise_floor(audio: np.ndarray, sample_rate: int = 16000) -> float:
        """Estimate the RMS noise floor from the quietest portions of the audio.

        Instead of using a fixed dB threshold, we analyze the actual audio to
        find the ambient noise level.  This adapts automatically to different
        environments (quiet room vs noisy classroom).

        Strategy: divide audio into short windows, sort by energy, and take
        the median of the bottom 20% as the noise floor estimate.  This is
        robust against speech segments inflating the estimate.
        """
        window_size = int(sample_rate * 0.02)  # 20ms windows
        if len(audio) < window_size * 5:
            # Too short to estimate — use conservative default
            return 10.0 ** (-40.0 / 20.0)

        n_windows = len(audio) // window_size
        rms_values = np.empty(n_windows, dtype=np.float32)
        for i in range(n_windows):
            start = i * window_size
            end = start + window_size
            rms_values[i] = np.sqrt(np.mean(audio[start:end] ** 2))

        # Sort and take median of bottom 20% (quietest windows = noise)
        rms_values.sort()
        bottom_count = max(1, n_windows // 5)
        noise_floor = float(np.median(rms_values[:bottom_count]))

        # Clamp to reasonable range: at least -60dB, at most -25dB
        min_floor = 10.0 ** (-60.0 / 20.0)  # 0.001
        max_floor = 10.0 ** (-25.0 / 20.0)  # 0.056
        return max(min_floor, min(noise_floor, max_floor))

    @staticmethod
    def _noise_gate(audio: np.ndarray, threshold_db: float = -40.0,
                    noise_floor: float | None = None) -> np.ndarray:
        """Gentle noise gate with soft-knee curve.

        Uses a smooth gain curve that transitions gradually from a mild
        attenuation to unity gain over a 6dB "knee" range.  The minimum
        gain is 0.2 (not silence) to preserve soft consonants and avoid
        destroying speech content that Whisper needs.

        If noise_floor is provided (from _estimate_noise_floor), the gate
        threshold is set relative to it (1.5× noise floor) instead of
        using the fixed dB value.
        """
        # Minimum gain: 0.2 instead of 0.05 — keeps quiet speech audible
        min_gain = 0.2

        if noise_floor is not None:
            # Set threshold at 1.5× the estimated noise floor (was 2×)
            # Less aggressive: only gate clearly-below-noise content
            linear_threshold = noise_floor * 1.5
        else:
            linear_threshold = 10.0 ** (threshold_db / 20.0)

        # Soft-knee range: 6dB below threshold to threshold
        knee_low = linear_threshold * 0.5  # -6dB below threshold

        # 20ms windows at 16kHz = 320 samples
        window_size = 320
        if len(audio) < window_size:
            return audio

        result = audio.copy()
        n_windows = len(audio) // window_size

        for i in range(n_windows):
            start = i * window_size
            end = start + window_size
            window_rms = np.sqrt(np.mean(audio[start:end] ** 2))

            if window_rms < knee_low:
                # Below threshold — mild attenuation (preserve content)
                result[start:end] *= min_gain
            elif window_rms < linear_threshold:
                # In the knee region — smooth transition (cosine interpolation)
                # Maps [knee_low, threshold] → [min_gain, 1.0]
                t = (window_rms - knee_low) / (linear_threshold - knee_low)
                # Smooth step using cosine curve (avoids discontinuities)
                gain = min_gain + (1.0 - min_gain) * (0.5 - 0.5 * np.cos(np.pi * t))
                result[start:end] *= gain
            # else: above threshold — keep original (gain=1.0)

        # Handle tail samples
        tail_start = n_windows * window_size
        if tail_start < len(audio):
            tail_rms = np.sqrt(np.mean(audio[tail_start:] ** 2))
            if tail_rms < knee_low:
                result[tail_start:] *= min_gain
            elif tail_rms < linear_threshold:
                t = (tail_rms - knee_low) / (linear_threshold - knee_low)
                gain = min_gain + (1.0 - min_gain) * (0.5 - 0.5 * np.cos(np.pi * t))
                result[tail_start:] *= gain

        return result.astype(np.float32)

    @staticmethod
    def _bandpass_voice_filter(audio: np.ndarray, sample_rate: int = 16000,
                               low_hz: float = 80.0, high_hz: float = 7500.0) -> np.ndarray:
        """FFT-based bandpass filter to isolate human voice frequencies.

        Zeroes out frequency bins outside [low_hz, high_hz], removing:
        - Sub-bass rumble, vibrations, HVAC hum (< 80 Hz)
        - Ultra-high noise above speech range (> 7500 Hz)

        The 80-7500 Hz range covers the full speech spectrum including:
        - Fundamental frequency and formants (80-3400 Hz)
        - Sibilant consonants: s, sh, ch, f, th (4000-8000 Hz)
        These high-frequency consonants are critical for Whisper to
        distinguish similar words.  Uses a smooth roll-off (raised cosine
        taper over 50 Hz) at the edges to avoid ringing artifacts.
        """
        if len(audio) < 64:
            return audio

        n = len(audio)
        spectrum = np.fft.rfft(audio)
        freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

        # Build gain mask with smooth roll-off edges (50 Hz taper)
        taper_width = 50.0  # Hz
        gain_mask = np.ones(len(freqs), dtype=np.float32)

        for i, f in enumerate(freqs):
            if f < low_hz - taper_width:
                gain_mask[i] = 0.0
            elif f < low_hz:
                # Smooth ramp up (raised cosine)
                t = (f - (low_hz - taper_width)) / taper_width
                gain_mask[i] = 0.5 - 0.5 * np.cos(np.pi * t)
            elif f > high_hz + taper_width:
                gain_mask[i] = 0.0
            elif f > high_hz:
                # Smooth ramp down
                t = (f - high_hz) / taper_width
                gain_mask[i] = 0.5 + 0.5 * np.cos(np.pi * t)

        spectrum *= gain_mask
        return np.fft.irfft(spectrum, n=n).astype(np.float32)

    @staticmethod
    def _spectral_denoise(audio: np.ndarray, sample_rate: int = 16000,
                          noise_estimate_ms: float = 300.0,
                          oversubtraction: float = 2.0,
                          spectral_floor: float = 0.02) -> np.ndarray:
        """Spectral subtraction noise reduction (Boll 1979).

        This is the core noise reduction method.  It works by:
        1. Computing the Short-Time Fourier Transform (STFT) of the audio
        2. Estimating the noise spectrum from the first ~300ms of the segment
           (which is typically silence/ambient noise before the child speaks)
        3. Subtracting the noise magnitude spectrum from each frame
        4. Reconstructing clean audio via inverse STFT (overlap-add)

        Effective against stationary noise (fans, AC, electrical hum, distant
        conversations).  Less effective against non-stationary noise (someone
        speaking right next to the mic at similar volume).

        Parameters:
            audio: Input audio (mono, float32)
            sample_rate: Sample rate in Hz
            noise_estimate_ms: Duration of initial audio to use as noise profile
            oversubtraction: How aggressively to subtract noise (1.0=exact, 2.0=aggressive)
            spectral_floor: Minimum spectral magnitude to prevent "musical noise" artifacts
        """
        if len(audio) < 1024:
            return audio

        # STFT parameters
        frame_size = 512  # 32ms at 16kHz — good time-frequency resolution for speech
        hop_size = frame_size // 2  # 50% overlap for smooth reconstruction
        window = np.hanning(frame_size).astype(np.float32)

        # Pad audio to ensure complete frames
        n_frames = (len(audio) - frame_size) // hop_size + 1
        if n_frames < 2:
            return audio

        # STFT: decompose audio into overlapping windowed frames
        frames_fft = []
        for i in range(n_frames):
            start = i * hop_size
            frame = audio[start:start + frame_size] * window
            frames_fft.append(np.fft.rfft(frame))

        # Estimate noise spectrum from initial frames
        noise_frames_count = max(1, int((noise_estimate_ms / 1000.0) * sample_rate / hop_size))
        noise_frames_count = min(noise_frames_count, n_frames // 3)  # Never use more than 1/3

        # Average magnitude spectrum of noise frames
        noise_spectrum = np.mean(
            [np.abs(frames_fft[i]) for i in range(noise_frames_count)],
            axis=0,
        )

        # Spectral subtraction with flooring
        clean_frames = []
        for frame_fft in frames_fft:
            magnitude = np.abs(frame_fft)
            phase = np.angle(frame_fft)

            # Subtract noise magnitude (with over-subtraction factor)
            clean_magnitude = magnitude - oversubtraction * noise_spectrum

            # Spectral floor: prevent negative magnitudes and "musical noise"
            # by clamping to a fraction of the original magnitude
            floor = spectral_floor * magnitude
            clean_magnitude = np.maximum(clean_magnitude, floor)

            # Reconstruct complex spectrum with original phase
            clean_fft = clean_magnitude * np.exp(1j * phase)
            clean_frames.append(np.fft.irfft(clean_fft, n=frame_size))

        # Overlap-add reconstruction
        output_length = (n_frames - 1) * hop_size + frame_size
        output = np.zeros(output_length, dtype=np.float32)
        window_sum = np.zeros(output_length, dtype=np.float32)

        for i, frame in enumerate(clean_frames):
            start = i * hop_size
            output[start:start + frame_size] += frame.astype(np.float32) * window
            window_sum[start:start + frame_size] += window ** 2

        # Normalize by window sum to compensate for overlap
        nonzero = window_sum > 1e-8
        output[nonzero] /= window_sum[nonzero]

        # Trim to original length
        return output[:len(audio)].astype(np.float32)

    @staticmethod
    def _pad_audio(audio: np.ndarray, sample_rate: int = 16000, min_duration_s: float = 1.5) -> np.ndarray:
        """Pad very short audio segments with silence to a minimum duration.

        Whisper's encoder processes 30-second mel spectrogram windows.  Very
        short segments (<1s) produce sparse spectrograms that confuse the
        decoder, causing hallucinations or garbled output.  Padding with
        silence to at least 1.5s gives the model enough context.
        """
        min_samples = int(sample_rate * min_duration_s)
        if len(audio) >= min_samples:
            return audio
        # Pad symmetrically (silence before and after) so speech is centered
        total_pad = min_samples - len(audio)
        pad_before = total_pad // 2
        pad_after = total_pad - pad_before
        return np.concatenate([
            np.zeros(pad_before, dtype=np.float32),
            audio,
            np.zeros(pad_after, dtype=np.float32),
        ])

    def _preprocess_audio(self, audio: np.ndarray) -> np.ndarray:
        """Full audio preprocessing pipeline before transcription.

        Order matters — each stage builds on the previous:
        1. Bandpass filter (80-7500 Hz): Remove frequencies outside speech range
        2. Spectral subtraction: Gentle removal of stationary background noise
        3. Noise gate (dynamic floor): Mild attenuation of residual noise
        4. Pre-emphasis: Boost consonant frequencies for clarity
        5. Normalize: Consistent volume level
        6. Pad: Ensure minimum duration for Whisper

        IMPORTANT: This pipeline must be minimally invasive.  Whisper was
        trained on full-bandwidth audio and handles moderate noise well.
        Over-processing degrades transcription accuracy more than noise does.

        NOTE: Steps 1-4 están deshabilitados porque degradaban la calidad
        del audio más de lo que ayudaban.  Se conserva el código para
        poder reactivarlos en el futuro si se mejoran los parámetros.
        """
        # --- DESHABILITADO: el procesamiento de ruido degrada el audio ---
        # 1. Bandpass — eliminate sub-bass rumble and ultra-high noise
        # audio = self._bandpass_voice_filter(audio, sample_rate=16000,
        #                                     low_hz=80.0, high_hz=7500.0)
        # 2. Spectral subtraction — gentle noise removal
        # audio = self._spectral_denoise(audio, sample_rate=16000,
        #                                noise_estimate_ms=300.0,
        #                                oversubtraction=1.0,
        #                                spectral_floor=0.08)
        # 3. Noise gate — mild, preserves soft consonants (min_gain=0.2)
        # noise_floor = self._estimate_noise_floor(audio, sample_rate=16000)
        # audio = self._noise_gate(audio, noise_floor=noise_floor)
        # 4. Pre-emphasis — boost consonants
        # audio = self._pre_emphasis(audio, coeff=0.97)
        # --- FIN DESHABILITADO ---

        # 5. DC offset removal — micrófonos USB baratos introducen un
        # desplazamiento constante que confunde a Whisper.  Una sola resta
        # del promedio limpia la señal sin tocar los formantes.
        audio = (audio - np.mean(audio)).astype(np.float32)
        # 6. Normalize — consistent level (necesario para Whisper)
        audio = self._normalize_audio(audio)
        # Clips de una sílaba (tijera, papel) alucinan menos con un poco de silencio.
        if len(audio) / 16000.0 < 1.2:
            audio = self._pad_audio(audio, sample_rate=16000, min_duration_s=1.5)
        return audio

    _LOW_LOGPROB_THRESHOLD: float = -0.9
    _HIGH_NO_SPEECH_THRESHOLD: float = 0.75

    def _transcribe(self, whisper_model: Any, audio_segment: np.ndarray) -> TranscriptionResult:
        empty = TranscriptionResult(text="")
        if whisper_model is None:
            return empty

        _dlog = get_debug_logger()

        raw_rms = float(np.sqrt(np.mean(audio_segment ** 2)))
        if raw_rms < 0.0005:
            save_named_transcript_wav(audio_segment, "", sample_rate=16000)
            return empty

        raw_audio_copy = audio_segment.copy() if _dlog else None
        audio_segment = self._preprocess_audio(audio_segment)
        processed_audio_copy = audio_segment.copy() if _dlog else None

        segments, _info = whisper_model.transcribe(
            audio_segment,
            language="es",
            vad_filter=False,
            beam_size=whisper_beam_size(),
            initial_prompt=self._WHISPER_INITIAL_PROMPT,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        text_parts = []
        logprobs: list[float] = []
        no_speech_probs: list[float] = []
        for segment in segments:
            text_parts.append(segment.text.strip())
            avg_lp = getattr(segment, "avg_logprob", None)
            if avg_lp is not None:
                logprobs.append(float(avg_lp))
            nsp = getattr(segment, "no_speech_prob", None)
            if nsp is not None:
                no_speech_probs.append(float(nsp))
        transcript = " ".join(part for part in text_parts if part).strip()
        transcript = self._filter_hallucinations(transcript)
        save_named_transcript_wav(audio_segment, transcript, sample_rate=16000)

        avg_logprob = float(np.mean(logprobs)) if logprobs else None
        no_speech_prob = float(np.mean(no_speech_probs)) if no_speech_probs else None
        low_confidence = False
        if transcript and avg_logprob is not None and avg_logprob < self._LOW_LOGPROB_THRESHOLD:
            low_confidence = True
        if transcript and no_speech_prob is not None and no_speech_prob > self._HIGH_NO_SPEECH_THRESHOLD:
            low_confidence = True

        if _dlog and raw_audio_copy is not None and processed_audio_copy is not None:
            _dlog.save_debug_audio(
                raw_audio=raw_audio_copy,
                processed_audio=processed_audio_copy,
                transcript_text=transcript,
                sample_rate=16000,
            )

        return TranscriptionResult(
            text=transcript,
            low_confidence=low_confidence,
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
        )

    @staticmethod
    def _filter_hallucinations(text: str) -> str:
        """Descarta transcripciones que son alucinaciones conocidas de Whisper.

        Whisper genera frases inventadas cuando recibe audio muy corto,
        ruidoso o casi silencioso.  Las más frecuentes son:
        - Créditos de subtítulos ("Subtítulos realizados por...", "Sous-titres...")
        - Agradecimientos genéricos ("Gracias por ver", "Thank you...")
        - Una sola palabra repetida N veces ("ruido ruido ruido")
        - Texto que es eco del initial_prompt
        """
        if not text:
            return ""

        low = text.lower().strip()

        # Frases basura conocidas (multilingüe porque Whisper a veces
        # cambia de idioma en las alucinaciones)
        _HALLUCINATION_PHRASES = [
            "subtítulos realizados",
            "subtitulos realizados",
            "subtítulos por",
            "sous-titres",
            "sous titres",
            "gracias por ver",
            "thanks for watching",
            "thank you for watching",
            "suscríbete",
            "subscribe",
            "like and subscribe",
            "amara.org",
            "www.",
            "http",
        ]
        for phrase in _HALLUCINATION_PHRASES:
            if phrase in low:
                return ""

        # Palabra única repetida (ej: "ruido ruido ruido", "no no no no")
        words = low.split()
        if len(words) >= 3 and len(set(words)) == 1:
            return ""

        # Texto demasiado corto para ser habla real (1 carácter suelto)
        if len(low) <= 1:
            return ""

        # Eco de prompts viejos / frases que Whisper copia del contexto.
        _PROMPT_ECHO = (
            "me gusta el peluche",
            "vamos a hacer algo divertido",
            "jugamos a las adivinanzas",
        )
        folded_words = " ".join(words)
        for echo in _PROMPT_ECHO:
            if echo in folded_words and len(words) <= 8:
                return ""

        return text

    def _load_vad(self, sample_rate: int):
        return SileroVadAdapter(sample_rate=sample_rate)


class SpeechWorker:
    PIPER_MODEL_NAME = "es_AR-daniela-high"
    PIPER_MODEL_HF_PATH = "es/es_AR/daniela/high"
    # Más alto = más lento. 1.20 = ritmo actual (pausado, menos “orden”).
    # Si sigue sonando apurada: probar 1.30 (cambio más marcado; puede arrastrar).
    PIPER_LENGTH_SCALE = 1.20
    PIPER_NOISE_SCALE = 0.667
    # Más alto = duraciones de sílaba menos rígidas (menos cadencia de mandato).
    PIPER_NOISE_W_SCALE = 0.98

    def __init__(
        self,
        output_device_index: int | None = None,
        message_queue: queue.Queue[WorkerMessage] | None = None,
        message_semaphore: threading.Semaphore | None = None,
        cloud_mode: bool = False,
        cloud_tts: Any = None,
    ) -> None:
        self._queue: queue.Queue[str] = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_windows = sys.platform.startswith("win")
        self._output_device_index = output_device_index
        self._message_queue = message_queue
        self._message_semaphore = message_semaphore
        self._piper_voice: Any = None
        self._idle_event = threading.Event()
        self._idle_event.set()  # Not speaking initially

        # Music playback state
        self._music_stop_event = threading.Event()
        self._music_generation = 0
        self._is_playing_music = False
        self._current_song_name: str | None = None

        # Cloud mode (#CLOUD-001)
        self._cloud_mode = cloud_mode
        self._cloud_tts = cloud_tts
        self._volume_limit = 100
        self._night_mode = False
        self._playback_generation = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        log_action("SpeechWorker", f"inicio (salida={self._output_device_index})")
        self._thread = threading.Thread(target=self._run, name="SpeechWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        log_action("SpeechWorker", "deteniendo...")
        self._stop_event.set()
        try:
            self._queue.put_nowait("")
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        log_action("SpeechWorker", "detenido")

    def is_busy(self) -> bool:
        return not self._idle_event.is_set() or self._is_playing_music

    def set_volume_limit(self, value: int) -> None:
        self._volume_limit = max(0, min(100, int(value)))

    def set_night_mode(self, enabled: bool) -> None:
        self._night_mode = bool(enabled)

    def interrupt_playback(self) -> None:
        """Corta TTS en curso (barge-in) sin matar el worker."""
        self._playback_generation += 1
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._idle_event.set()

    @staticmethod
    def _strip_tts_markup(text: str) -> str:
        cleaned = re.sub(r"\[[^\]]*\]", "", text)
        cleaned = re.sub(r"NOTIFY_PARENT\s*:?\s*.*$", "", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    @staticmethod
    def _prepare_tts_text(text: str) -> str:
        cleaned = re.sub(r"\s{2,}", " ", text).strip()
        if not cleaned:
            return ""
        if cleaned[-1] not in ".!?…":
            cleaned += "."
        return cleaned

    def speak(self, text: str) -> None:
        speech_text = self._prepare_tts_text(self._strip_tts_markup((text or "").strip()))
        if not speech_text:
            return
        self._idle_event.clear()
        try:
            self._queue.put_nowait(speech_text)
            log_action("SpeechWorker", f"enqueued TTS ({len(speech_text)} chars)")
        except queue.Full:
            self._idle_event.set()
            log_action("SpeechWorker", "cola TTS llena, se descarta frase")

    def set_output_device(self, output_device_index: int | None) -> None:
        self._output_device_index = output_device_index

    def speak_and_wait(self, text: str, timeout: float = 30.0) -> None:
        """Queue text for speaking and block until playback finishes."""
        speech_text = self._prepare_tts_text(self._strip_tts_markup((text or "").strip()))
        if not speech_text:
            return
        self._idle_event.clear()
        try:
            self._queue.put_nowait(speech_text)
        except queue.Full:
            self._idle_event.set()
            return
        self._idle_event.wait(timeout=timeout)

    def _log(self, text: str) -> None:
        """Log to UI message queue if available, otherwise print."""
        print(f"[SpeechWorker] {text}", flush=True)
        log_action("SpeechWorker", text)
        if self._message_queue is not None:
            _queue_message_with_semaphore(
                self._message_queue, self._message_semaphore, "log", f"[TTS] {text}"
            )

    @staticmethod
    def _resample_audio(audio_array: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Resample audio using numpy linear interpolation (no scipy needed).

        Works for both mono (N,1) and multi-channel (N,C) arrays.
        """
        if orig_sr == target_sr:
            return audio_array
        ratio = target_sr / orig_sr
        orig_len = audio_array.shape[0]
        new_len = int(orig_len * ratio)
        if new_len == 0:
            return audio_array
        old_indices = np.arange(orig_len)
        new_indices = np.linspace(0, orig_len - 1, new_len)
        if audio_array.ndim == 1:
            return np.interp(new_indices, old_indices, audio_array).astype(np.float32)
        # Multi-channel: interpolate each channel independently
        channels = audio_array.shape[1]
        resampled = np.empty((new_len, channels), dtype=np.float32)
        for ch in range(channels):
            resampled[:, ch] = np.interp(new_indices, old_indices, audio_array[:, ch])
        return resampled

    def _find_supported_output_config(
        self, sample_rate: int, channels: int
    ) -> tuple[int, str, int]:
        """Return (samplerate, dtype, channels) that the output device accepts.

        Raspberry Pi 5 con el parlante actual: ALSA pide int16 estéreo a 48 kHz.
        En Linux no se negocia otro formato. En Windows se prueba el dispositivo.
        """
        if sys.platform.startswith("linux"):
            return 48000, "int16", 2

        rates: list[int] = []
        for sr in (sample_rate, 48000, 44100, 22050, 16000):
            if sr not in rates:
                rates.append(sr)

        if sys.platform.startswith("linux"):
            dtypes = ("int16", "float32")
            raw_channels = (2, 1) if channels == 1 else (channels, 2, 1)
        else:
            dtypes = ("float32", "int16")
            raw_channels = (channels, 2) if channels == 1 else (channels, 1)

        channel_options: list[int] = []
        for ch in raw_channels:
            if ch > 0 and ch not in channel_options:
                channel_options.append(ch)

        for sr in rates:
            for dtype in dtypes:
                for ch in channel_options:
                    try:
                        sd.check_output_settings(
                            device=self._output_device_index,
                            samplerate=float(sr),
                            channels=ch,
                            dtype=dtype,
                        )
                        return sr, dtype, ch
                    except Exception:
                        continue
        return 48000, "int16", 2

    def _find_supported_samplerate(self, sample_rate: int, channels: int) -> int:
        """Compat: only the sample rate from the full ALSA/WASAPI probe."""
        sr, _dtype, _ch = self._find_supported_output_config(sample_rate, channels)
        return sr

    @staticmethod
    def _adapt_playback_audio(
        audio_array: np.ndarray,
        orig_sr: int,
        target_sr: int,
        target_dtype: str,
        target_channels: int,
    ) -> tuple[np.ndarray, int]:
        """Resample, upmix/downmix and convert dtype for the output device."""
        if audio_array.ndim == 1:
            audio_array = audio_array.reshape(-1, 1)
        if audio_array.dtype != np.float32:
            if np.issubdtype(audio_array.dtype, np.integer):
                info = np.iinfo(audio_array.dtype)
                audio_array = audio_array.astype(np.float32) / float(info.max)
            else:
                audio_array = audio_array.astype(np.float32)

        audio_array = SpeechWorker._resample_audio(audio_array, orig_sr, target_sr)

        src_ch = audio_array.shape[1]
        if target_channels > src_ch:
            if src_ch == 1:
                audio_array = np.repeat(audio_array, target_channels, axis=1)
            else:
                pad = np.zeros(
                    (audio_array.shape[0], target_channels - src_ch),
                    dtype=audio_array.dtype,
                )
                audio_array = np.concatenate([audio_array, pad], axis=1)
        elif target_channels < src_ch:
            audio_array = audio_array[:, :target_channels]

        if target_dtype == "int16":
            clipped = np.clip(audio_array, -1.0, 1.0)
            audio_array = (clipped * 32767.0).astype(np.int16)
        else:
            audio_array = audio_array.astype(np.float32)

        return np.ascontiguousarray(audio_array), target_sr

    def _play_wav_via_output_stream(
        self,
        audio_array: np.ndarray,
        sample_rate: int,
        music_generation: int | None = None,
    ) -> None:
        """Play audio using a dedicated OutputStream to avoid conflicts with AudioWorker's InputStream.

        sd.play() uses the *default* PortAudio output stream which can collide
        with an already-open InputStream on some backends.  Opening our own
        OutputStream with an explicit device avoids this.

        Raspberry Pi ALSA frequently rejects float32/mono even after resampling
        to 48000 Hz (PaErrorCode -9994).  Probe rate+dtype+channels and retry
        with int16 stereo if opening the stream still fails.

        ``music_generation``: si se pasa, esta reproducción es música y se
        puede cortar con stop_music(). El TTS no lo pasa, así una pausa de
        canción no silencia la voz después.
        """
        if audio_array.ndim == 1:
            audio_array = audio_array.reshape(-1, 1)
        if audio_array.dtype != np.float32:
            info = np.iinfo(audio_array.dtype)
            audio_array = audio_array.astype(np.float32) / float(info.max)

        orig_channels = audio_array.shape[1] if audio_array.ndim > 1 else 1
        from session_policy import apply_gain, effective_volume_limit, gain_from_limit

        limit = effective_volume_limit(self._volume_limit, self._night_mode)
        audio_array = apply_gain(audio_array, gain_from_limit(limit))
        playback_gen = self._playback_generation
        probed = self._find_supported_output_config(sample_rate, orig_channels)
        configs: list[tuple[int, str, int]] = []
        for cfg in (probed, (48000, "int16", 2), (44100, "int16", 2)):
            if cfg not in configs:
                configs.append(cfg)

        last_exc: Exception | None = None
        for device_sr, dtype, channels in configs:
            play_audio, play_sr = self._adapt_playback_audio(
                audio_array,
                orig_sr=sample_rate,
                target_sr=device_sr,
                target_dtype=dtype,
                target_channels=channels,
            )
            if (device_sr, dtype, channels) != (sample_rate, "float32", orig_channels):
                self._log(
                    f"Ajustando audio {sample_rate} Hz/{orig_channels}ch/float32 → "
                    f"{play_sr} Hz/{channels}ch/{dtype}"
                )

            finished = threading.Event()
            pos = [0]

            def _callback(
                outdata: np.ndarray,
                frames: int,
                _time_info: Any,
                _status: Any,
                _audio: np.ndarray = play_audio,
                _finished: threading.Event = finished,
                _pos: list[int] = pos,
            ) -> None:
                if self._stop_event.is_set():
                    _finished.set()
                    raise sd.CallbackStop()
                if playback_gen != self._playback_generation:
                    _finished.set()
                    raise sd.CallbackStop()
                if music_generation is not None and (
                    self._music_stop_event.is_set()
                    or self._music_generation != music_generation
                ):
                    _finished.set()
                    raise sd.CallbackStop()
                start = _pos[0]
                end = start + frames
                chunk = _audio[start:end]
                if len(chunk) < frames:
                    outdata[: len(chunk)] = chunk
                    outdata[len(chunk) :] = 0
                    _finished.set()
                    raise sd.CallbackStop()
                outdata[:] = chunk
                _pos[0] = end

            try:
                with sd.OutputStream(
                    samplerate=play_sr,
                    channels=channels,
                    dtype=dtype,
                    device=self._output_device_index,
                    callback=_callback,
                ):
                    finished.wait(timeout=len(play_audio) / play_sr + 5.0)
                return
            except Exception as exc:
                last_exc = exc
                self._log(
                    f"Salida {dtype}/{channels}ch/{play_sr} Hz falló: {exc}"
                )

        if last_exc is not None:
            raise last_exc

    def _run(self) -> None:
        log_action("SpeechWorker", "tarea _run comenzada")
        if self._cloud_mode:
            self._log("Modo NUBE activo — usando Google gTTS (con caché local)")
        else:
            # Try to load piper neural TTS (best quality, cross-platform, edge-optimized)
            self._try_load_piper()
            if self._piper_voice is not None:
                self._log("piper-tts neural cargado correctamente")
            else:
                self._log("piper-tts no disponible, usando TTS de plataforma")

        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.25)
            except queue.Empty:
                self._idle_event.set()
                continue

            if self._stop_event.is_set() or not text:
                self._idle_event.set()
                continue

            try:
                self._log(f"Sintetizando: {text}")
                _dlog = get_debug_logger()
                _t_synth = time.monotonic()
                if _dlog:
                    _dlog.log_input("TTS_SYNTH", f"engine={'gTTS' if self._cloud_mode else ('piper' if self._piper_voice else ('sapi' if self._is_windows else 'espeak'))}, text=\"{text}\"")
                if self._cloud_mode and self._cloud_tts is not None:
                    self._speak_cloud(text)
                elif self._piper_voice is not None:
                    self._speak_piper(text)
                elif self._is_windows:
                    self._speak_windows(text)
                else:
                    self._speak_linux(text)
                if _dlog:
                    _dlog.log_output("TTS_SYNTH", "Síntesis + reproducción completada", elapsed_ms=(time.monotonic() - _t_synth) * 1000)
                self._log("Reproducción completada")
            except Exception as exc:
                self._log(f"Error TTS: {exc}")

            # Signal idle when queue is drained after playback
            if self._queue.empty():
                self._idle_event.set()
        log_action("SpeechWorker", "tarea _run finalizada")

    def _try_load_piper(self) -> None:
        """Try to initialise piper-tts neural TTS for natural-sounding speech."""
        try:
            from piper.voice import PiperVoice
        except ImportError:
            try:
                from piper import PiperVoice  # type: ignore[attr-defined]
            except (ImportError, AttributeError):
                return

        try:
            model_path = self._ensure_piper_model()
            self._piper_voice = PiperVoice.load(str(model_path))
        except Exception as exc:
            self._log(f"Error cargando modelo piper: {exc}")
            self._piper_voice = None

    @staticmethod
    def _ensure_piper_model() -> Path:
        """Return path to the piper ONNX model, downloading it on first use."""
        model_name = SpeechWorker.PIPER_MODEL_NAME
        cache_dir = Path.home() / ".edge_ai_models" / "piper"
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_file = cache_dir / f"{model_name}.onnx"
        config_file = cache_dir / f"{model_name}.onnx.json"

        if model_file.exists() and config_file.exists():
            return model_file

        base_url = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{SpeechWorker.PIPER_MODEL_HF_PATH}/{model_name}"
        )

        for suffix, target in [(".onnx", model_file), (".onnx.json", config_file)]:
            if not target.exists():
                urllib.request.urlretrieve(f"{base_url}{suffix}", target)

        return model_file

    def _speak_piper(self, text: str) -> None:
        """Synthesize speech with piper neural TTS v1.4+ -> direct float32 -> sounddevice."""
        audio_chunks: list[np.ndarray] = []
        sample_rate: int = 22050  # default; updated from first chunk

        try:
            from piper.config import SynthesisConfig
            syn_config = SynthesisConfig(
                length_scale=SpeechWorker.PIPER_LENGTH_SCALE,
                noise_scale=SpeechWorker.PIPER_NOISE_SCALE,
                noise_w_scale=SpeechWorker.PIPER_NOISE_W_SCALE,
            )
        except Exception:
            syn_config = None

        synth_kwargs = {"syn_config": syn_config} if syn_config is not None else {}
        for chunk in self._piper_voice.synthesize(text, **synth_kwargs):
            audio_chunks.append(chunk.audio_float_array)
            sample_rate = chunk.sample_rate

        if not audio_chunks:
            self._log("Piper no generó audio para el texto dado")
            return

        audio_array = np.concatenate(audio_chunks).astype(np.float32)
        # audio_float_array is already in [-1.0, 1.0] range
        self._play_wav_via_output_stream(audio_array, sample_rate)

    # ------------------------------------------------------------------
    # Music playback
    # ------------------------------------------------------------------

    def stop_music(self) -> None:
        """Detiene la reproducción de música en curso (no corta el TTS)."""
        self._music_generation += 1
        self._music_stop_event.set()
        self._is_playing_music = False
        self._current_song_name = None
        self._log("Música detenida")

    def play_music(self, filename: str | None = None) -> bool:
        """Reproduce una canción de la carpeta music/."""
        music_dir = APP_DIR / "music"
        if not music_dir.exists():
            self._log("Carpeta music/ no existe")
            return False

        allowed_ext = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
        if filename:
            file_path = music_dir / filename
            if not file_path.exists():
                self._log(f"Canción no encontrada: {filename}")
                return False
        else:
            files = [f for f in sorted(music_dir.iterdir()) if f.suffix.lower() in allowed_ext]
            if not files:
                self._log("No hay canciones disponibles en music/")
                return False
            import random
            file_path = random.choice(files)

        return self.play_audio_file(file_path)

    def play_audio_file(self, file_path: Path | str) -> bool:
        """Carga y reproduce cualquier archivo de audio (mp3, m4a, wav, ogg, flac)."""
        path = Path(file_path)
        if not path.exists():
            self._log(f"Archivo no encontrado: {path}")
            return False

        self.stop_music()
        self._music_generation += 1
        my_generation = self._music_generation
        self._music_stop_event.clear()
        self._is_playing_music = True
        self._current_song_name = path.name
        self._log(f"Reproduciendo música: {path.name}")
        try:
            from api_server import robot_state as _rs
            _rs.push_notification(
                "musica",
                f"Reproduciendo: {path.name}",
                extra={"filename": path.name},
            )
        except Exception:
            pass

        audio_array: np.ndarray | None = None
        sample_rate: int = 44100

        # 1. Intentar con soundfile (WAV, OGG, FLAC, MP3)
        try:
            import soundfile as sf
            data, sr = sf.read(str(path), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            audio_array = data.astype(np.float32)
            sample_rate = sr
        except Exception:
            pass

        # 2. Fallback con PyAV (M4A, AAC, etc.)
        if audio_array is None:
            try:
                import av
                container = av.open(str(path))
                stream = container.streams.audio[0]
                sample_rate = stream.rate
                frames = []
                for frame in container.decode(stream):
                    arr = frame.to_ndarray()
                    if arr.ndim > 1:
                        arr = arr.mean(axis=0)
                    frames.append(arr)
                if frames:
                    audio_array = np.concatenate(frames).astype(np.float32)
                    max_abs = np.max(np.abs(audio_array))
                    if max_abs > 1.0:
                        audio_array = audio_array / max_abs
            except Exception as e:
                self._log(f"Error decodificando audio {path.name}: {e}")
                self._is_playing_music = False
                return False

        if audio_array is None or len(audio_array) == 0:
            self._log(f"Audio vacío en {path.name}")
            self._is_playing_music = False
            return False

        self._idle_event.clear()
        try:
            self._play_wav_via_output_stream(
                audio_array,
                sample_rate,
                music_generation=my_generation,
            )
            self._log("Reproducción de música completada")
        except Exception as exc:
            self._log(f"Error en reproducción de música: {exc}")
        finally:
            self._is_playing_music = False
            self._current_song_name = None
            if self._music_generation == my_generation:
                self._music_stop_event.clear()
            self._idle_event.set()

        return True

    def _speak_cloud(self, text: str) -> None:
        """Sintetiza voz con Google gTTS (con caché local) vía CloudTTS."""
        if self._cloud_tts is None:
            self._log("CloudTTS no disponible")
            return

        result = self._cloud_tts.synthesize_to_audio(text)
        if result is None:
            self._log("gTTS no generó audio para el texto dado")
            return

        audio_array, sample_rate = result
        self._play_wav_via_output_stream(audio_array, sample_rate)

    def _speak_windows(self, text: str) -> None:
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = wav_file.name

        try:
            escaped_text = saxutils.escape(text)
            safe_wav_path = wav_path.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Speech;"
                f"$out = '{safe_wav_path}';"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$voices = @($s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' });"
                "$preferredNames = @('Microsoft Helena Desktop', 'Microsoft Sabina Desktop', 'Helena', 'Sabina', 'Laura', 'Paloma');"
                "$selected = $null;"
                "foreach ($name in $preferredNames) {"
                "  $selected = $voices | Where-Object { $_.VoiceInfo.Name -like ('*' + $name + '*') } | Select-Object -First 1;"
                "  if ($selected) { break }"
                "};"
                "if ($selected) { $s.SelectVoice($selected.VoiceInfo.Name) } elseif ($voices) { $s.SelectVoice($voices[0].VoiceInfo.Name) }"
                "$s.Rate = -2;"
                "$s.Volume = 100;"
                "$s.SetOutputToWaveFile($out);"
                f"$decoded = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_text}'));"
                f"$ssml = '<speak version=\'1.0\' xml:lang=\'es-ES\'><prosody rate=\'-10%\' pitch=\'+0st\'>{escaped_text}</prosody></speak>';"
                "try { $s.SpeakSsml($ssml) } catch { $s.Speak($decoded) };"
                "$s.SetOutputToDefaultAudioDevice();"
                "$s.Dispose();"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            subprocess.run(
                ["powershell", "-NoProfile", "-EncodedCommand", encoded],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with wave.open(wav_path, "rb") as wav_reader:
                frame_count = wav_reader.getnframes()
                sample_rate = wav_reader.getframerate()
                sample_width = wav_reader.getsampwidth()
                channel_count = wav_reader.getnchannels()
                audio_data = wav_reader.readframes(frame_count)

            dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(sample_width)
            if dtype is None:
                return

            audio_array = np.frombuffer(audio_data, dtype=dtype)
            if channel_count > 1:
                audio_array = audio_array.reshape(-1, channel_count)

            self._play_wav_via_output_stream(audio_array, sample_rate)
        finally:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _speak_linux(self, text: str) -> None:
        """TTS via espeak-ng (pre-installed on Raspberry Pi OS) -> WAV -> sounddevice."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = wav_file.name

        try:
            subprocess.run(
                ["espeak-ng", "-v", "es", "-s", "140", "-w", wav_path, text],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with wave.open(wav_path, "rb") as wav_reader:
                frame_count = wav_reader.getnframes()
                sample_rate = wav_reader.getframerate()
                sample_width = wav_reader.getsampwidth()
                channel_count = wav_reader.getnchannels()
                audio_data = wav_reader.readframes(frame_count)

            dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(sample_width)
            if dtype is None:
                return

            audio_array = np.frombuffer(audio_data, dtype=dtype)
            if channel_count > 1:
                audio_array = audio_array.reshape(-1, channel_count)

            self._play_wav_via_output_stream(audio_array, sample_rate)
        finally:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass


class SileroVadAdapter:
    """Voice activity detection with streaming hysteresis.

    Uses Silero's 512-sample (32 ms @ 16 kHz) probability head instead of
    ``get_speech_timestamps`` (batch API). Falls back to RMS energy.
    """

    CHUNK_SAMPLES = 512
    START_THRESHOLD = 0.50
    CONTINUE_THRESHOLD = 0.35
    ENERGY_START = 0.012
    ENERGY_CONTINUE = 0.006

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._mode = "energy"
        self._model = None
        self._in_speech = False
        self._remainder = np.zeros(0, dtype=np.float32)
        self._load()

    def reset(self) -> None:
        self._in_speech = False
        self._remainder = np.zeros(0, dtype=np.float32)

    def _load(self) -> None:
        machine = platform.machine().lower()
        if sys.platform.startswith("linux") and machine in ("aarch64", "arm64"):
            # torch/silero en el proceso principal también puede Bus error en Pi 5.
            self._mode = "energy"
            return
        try:
            from silero_vad import load_silero_vad

            self._model = load_silero_vad()
            self._mode = "silero"
        except Exception:
            self._mode = "energy"

    def has_speech(self, audio_block: np.ndarray) -> bool:
        if self._mode == "silero" and self._model is not None:
            try:
                return self._streaming_speech(audio_block)
            except Exception:
                return self._energy_speech(audio_block)
        return self._energy_speech(audio_block)

    def _streaming_speech(self, audio_block: np.ndarray) -> bool:
        audio = np.concatenate(
            [self._remainder, np.asarray(audio_block, dtype=np.float32).reshape(-1)]
        )
        chunk = self.CHUNK_SAMPLES
        n_full = (len(audio) // chunk) * chunk
        self._remainder = audio[n_full:]
        if n_full == 0:
            return self._in_speech

        max_prob = 0.0
        for start in range(0, n_full, chunk):
            piece = audio[start:start + chunk]
            tensor = self._to_tensor(piece)
            prob = self._model(tensor, self.sample_rate)
            if hasattr(prob, "item"):
                prob = float(prob.item())
            else:
                prob = float(prob)
            if prob > max_prob:
                max_prob = prob

        threshold = self.CONTINUE_THRESHOLD if self._in_speech else self.START_THRESHOLD
        self._in_speech = max_prob >= threshold
        return self._in_speech

    def _energy_speech(self, audio_block: np.ndarray) -> bool:
        if audio_block.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(audio_block), dtype=np.float32)))
        threshold = self.ENERGY_CONTINUE if self._in_speech else self.ENERGY_START
        self._in_speech = rms > threshold
        return self._in_speech

    @staticmethod
    def _to_tensor(audio_block: np.ndarray):
        try:
            import torch

            return torch.from_numpy(np.asarray(audio_block, dtype=np.float32))
        except Exception:
            return np.asarray(audio_block, dtype=np.float32)