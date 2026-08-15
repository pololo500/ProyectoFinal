from __future__ import annotations

import base64
import json
import queue
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
except ImportError as exc:  # pragma: no cover - runtime dependency check.
    raise RuntimeError("spacy es requerido para la PoC") from exc

from debug_logger import get_debug_logger


@dataclass(frozen=True)
class WorkerMessage:
    kind: str
    payload: Any


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
    def __init__(self, intents: dict[str, dict[str, Any]]) -> None:
        self.intents = intents
        self.nlp = self._load_spacy_model()
        # Current observed emotion context (label, score), updated externally
        # Example: {"label": "feliz", "score": 0.82}
        self.current_emotion: dict[str, Any] | None = None
        # Pre-compute spaCy docs for all intent examples to avoid
        # reprocessing on every dispatch call (significant CPU save).
        self._example_docs: dict[str, list[tuple[str, Any]]] = {}
        for intent_name, intent_def in self.intents.items():
            examples = intent_def.get("examples", [])
            self._example_docs[intent_name] = [
                (ex, self.nlp(ex)) for ex in examples
            ]

    @classmethod
    def from_file(cls, path: Path) -> "IntentDispatcher":
        if path.exists():
            intents = json.loads(path.read_text(encoding="utf-8"))
        else:
            # Default intents now may include optional emotion requirements
            intents = {
                "greeting": {
                    "examples": ["hola", "buenos dias", "hey"],
                    "response": "Hola, estoy escuchando.",
                    # Accept when user is neutral or happy (OR logic)
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
        # Prioritize es_core_news_md (20k word vectors for high-accuracy semantic matching).
        # Falls back to es_core_news_sm, then blank('es') if not found.
        for model_name in ("es_core_news_md", "es_core_news_sm"):
            try:
                return spacy.load(model_name)
            except Exception:
                continue
        return spacy.blank("es")

    # Minimum confidence to accept an intent match.  Matches below this
    # threshold are returned as "unknown" so the fallback LLM can handle them.
    # 0.45 is calibrated for es_core_news_md: low enough for exact keyword
    # matches ("hola" → greeting) but high enough to reject spurious semantic
    # similarities ("el gato fue a la luna" → play @ 0.31).
    MIN_CONFIDENCE: float = 0.45

    def dispatch(self, text: str, emotion: dict[str, Any] | None = None) -> dict[str, Any]:
        _dlog = get_debug_logger()
        candidate_text = (text or "").strip()
        if not candidate_text:
            return {"intent_name": "unknown", "confidence": 0.0, "response": ""}

        if _dlog:
            _dlog.log_input("INTENT_DISPATCH", f"text=\"{candidate_text}\"")
        _t0 = time.monotonic()
        source_doc = self.nlp(candidate_text)
        best_match = {"intent_name": "unknown", "confidence": 0.0, "response": ""}

        # Use provided emotion context or the last observed one
        emotion_context = emotion if emotion is not None else self.current_emotion

        for intent_name, intent_definition in self.intents.items():
            response = intent_definition.get("response", "")
            required_emotions = intent_definition.get("emotions")
            emotion_threshold = float(intent_definition.get("emotion_threshold", 0.0))
            cached_examples = self._example_docs.get(intent_name, [])
            for _example_text, example_doc in cached_examples:
                similarity = self._similarity(source_doc, example_doc)
                # --- DESHABILITADO: el filtro por emociones no funciona bien ---
                # Si se reactiva, verificar que las emociones detectadas sean
                # confiables antes de usarlas para filtrar intents.
                # if required_emotions:
                #     if not emotion_context:
                #         # no emotion info -> skip this intent
                #         continue
                #     label = str(emotion_context.get("label", "")).lower()
                #     score = float(emotion_context.get("score", 0.0))
                #     matches_emotion = any(label == req.lower() and score >= emotion_threshold for req in required_emotions)
                #     if not matches_emotion:
                #         continue
                # --- FIN DESHABILITADO ---

                if similarity > best_match["confidence"]:
                    best_match = {
                        "intent_name": intent_name,
                        "confidence": float(similarity),
                        "response": response,
                    }

        # Reject low-confidence matches — let the fallback LLM handle them
        if best_match["confidence"] < self.MIN_CONFIDENCE:
            if _dlog:
                _dlog.log_output(
                    "INTENT_DISPATCH",
                    f"rejected={best_match['intent_name']} conf={best_match['confidence']:.3f} < {self.MIN_CONFIDENCE} → unknown",
                    elapsed_ms=(time.monotonic() - _t0) * 1000,
                )
            return {"intent_name": "unknown", "confidence": best_match["confidence"], "response": ""}

        if _dlog:
            _dlog.log_output(
                "INTENT_DISPATCH",
                f"intent={best_match['intent_name']} conf={best_match['confidence']:.3f}",
                elapsed_ms=(time.monotonic() - _t0) * 1000,
            )
        return best_match

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

    # Umbrales de silencio
    NORMAL_SILENCE: float = 1.8
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
        # Capture at a reduced frame rate to lower CPU usage (frames per second)
        # 3 fps is optimal for RPi 5: balances responsiveness vs CPU load
        self.frame_rate = 3

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="CameraWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

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

        try:
            # Auto-detect capture backend: DirectShow on Windows, V4L2 on Linux/RPi
            if sys.platform.startswith("win"):
                capture_backend = getattr(cv2, "CAP_DSHOW", 0)
            else:
                capture_backend = getattr(cv2, "CAP_V4L2", 0)
            capture = cv2.VideoCapture(self.camera_index, capture_backend)
            if not capture.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {self.camera_index}")
            # Force lower resolution to reduce USB bandwidth and MediaPipe CPU load
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            # Ruta clasica de MediaPipe (API solutions).
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
                # Fallback obligatorio: MediaPipe Tasks Face Landmarker.
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

                if face_mesh_enabled and face_mesh is not None and mp_drawing is not None and mp_face_mesh is not None:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = face_mesh.process(rgb_frame)

                    if result.multi_face_landmarks:
                        for face_landmarks in result.multi_face_landmarks:
                            mp_drawing.draw_landmarks(
                                image=rgb_frame,
                                landmark_list=face_landmarks,
                                connections=mp_face_mesh.FACEMESH_TESSELATION,
                                landmark_drawing_spec=drawing_spec,
                                connection_drawing_spec=connection_spec,
                            )

                    annotated_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
                    self._push_frame(annotated_frame)
                elif tasks_face_enabled and tasks_landmarker is not None:
                    annotated_frame, emotion_payload = self._process_tasks_frame(tasks_landmarker, frame)
                    self._push_frame(annotated_frame)

                    if emotion_payload is not None:
                        now = time.monotonic()
                        emotion_label = emotion_payload.get("label", "desconocida")
                        emotion_score = float(emotion_payload.get("score", 0.0))
                        if (now - last_emotion_log_ts) >= 3.0 or emotion_label != last_emotion_label:
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

                # Yield CPU briefly to ensure audio threads get processing time
                time.sleep(0.005)

        except Exception as exc:
            self.models_loaded_event.set()
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


class AudioWorker:
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

        # Game engine for multi-turn interactive games (#EPIC-006)
        try:
            from game_engine import GameEngine
            self.game_engine: Any = GameEngine()
        except ImportError:
            self.game_engine = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="AudioWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        sample_rate = 16000
        block_duration_seconds = 0.5
        block_size = int(sample_rate * block_duration_seconds)
        # Base silence threshold for toddlers (2-4 years): they produce
        # shorter utterances with longer pauses between words.
        # This is dynamically adjusted by EmotionReactor based on detected emotion.
        silence_threshold_seconds = self.emotion_reactor.NORMAL_SILENCE
        circular_buffer: deque[np.ndarray] = deque(maxlen=int(sample_rate * 6))
        current_segment: list[np.ndarray] = []
        silence_seconds = 0.0
        speech_active = False

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
            whisper_model = self._load_whisper_model()
        else:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: modo NUBE activo — omitiendo carga de Whisper local",
            )
        vad = self._load_vad(sample_rate)

        # Load fallback LLM sequentially after Whisper + VAD (solo modo local)
        if not self.cloud_mode and self.fallback_llm is not None:
            _queue_message_with_semaphore(
                self.message_queue, self.message_semaphore, "log",
                "AudioWorker: cargando LLM de fallback...",
            )
            try:
                self.fallback_llm.load()
            except Exception as exc:
                _queue_message_with_semaphore(
                    self.message_queue, self.message_semaphore, "log",
                    f"AudioWorker: LLM de fallback no disponible: {exc}",
                )

        _dlog = get_debug_logger()
        if _dlog:
            llm_status = "disponible" if (self.fallback_llm and self.fallback_llm.is_available) else "no disponible"
            _dlog.log_output("AUDIO_INIT", f"AudioWorker modelos cargados (Whisper + VAD + LLM={llm_status})")
        audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=32)

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Audio callback: {status}")
            try:
                audio_block = indata[:, 0].copy()
                audio_queue.put_nowait(audio_block)
            except queue.Full:
                pass

        if self.microphone_device_index == -1 or self.microphone_device_index is None:
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
            return

        try:
            with sd.InputStream(
                device=self.microphone_device_index,
                channels=1,
                samplerate=sample_rate,
                blocksize=block_size,
                dtype="float32",
                callback=callback,
            ):
                _queue_message_with_semaphore(
                    self.message_queue,
                    self.message_semaphore,
                    "status",
                    {
                        "mic": f"{self.microphone_device_index} activo",
                        "volume": 0,
                    },
                )
                _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", "silero-vad: escuchando...")

                while not self._stop_event.is_set():
                    try:
                        audio_block = audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    circular_buffer.append(audio_block)
                    
                    # Calculate volume (0-100%) using RMS, safely handling any unexpected NaN/Inf
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
                        {
                            "mic": f"{self.microphone_device_index} activo",
                            "volume": volume_pct,
                        },
                    )

                    speech_detected = vad.has_speech(audio_block)

                    # Adaptive silence threshold based on current emotion (#EPIC-005 CA#2)
                    emotion_context = getattr(self.intent_dispatcher, "current_emotion", None)
                    silence_threshold_seconds = self.emotion_reactor.get_silence_threshold(emotion_context)

                    if speech_detected:
                        if not speech_active:
                            speech_active = True
                            # Pre-roll: incluir hasta 2 bloques previos (~1.0s) del buffer circular
                            # para evitar que se corte la primera sílaba o palabra al empezar a hablar
                            buf_list = list(circular_buffer)
                            pre_roll = buf_list[:-1][-2:] if len(buf_list) > 1 else []
                            current_segment = pre_roll + [audio_block]
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "log",
                                f"silero-vad: escuchando... (umbral silencio: {silence_threshold_seconds:.1f}s)",
                            )
                        else:
                            current_segment.append(audio_block)
                        silence_seconds = 0.0
                    elif speech_active:
                        current_segment.append(audio_block)
                        silence_seconds += block_duration_seconds
                        if silence_seconds >= silence_threshold_seconds:
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "log",
                                "silero-vad: silencio detectado, cortando audio",
                            )
                            segment_audio = np.concatenate(current_segment, axis=0) if current_segment else np.array([], dtype=np.float32)
                            speech_active = False
                            silence_seconds = 0.0
                            current_segment = []
                            circular_buffer.clear()
                            self._handle_segment(segment_audio, whisper_model, audio_queue)

        except Exception as exc:
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en micrófono: {exc}")
            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "status",
                {"mic": "error"},
            )

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
            if self.cloud_mode and self.cloud_stt is not None:
                if _dlog:
                    _dlog.log_input("TRANSCRIPTION", f"Audio ({segment_duration_s:.1f}s) [CLOUD]")
                raw_text = self.cloud_stt.transcribe(audio_segment)
            else:
                if _dlog:
                    _dlog.log_input("TRANSCRIPTION", f"Audio ({segment_duration_s:.1f}s) [LOCAL]")
                raw_text = self._transcribe(whisper_model, audio_segment)
            if _dlog:
                _dlog.log_output("TRANSCRIPTION", f"\"{raw_text}\"", elapsed_ms=(time.monotonic() - _t_transcribe) * 1000)
            if not raw_text.strip():
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
                except Exception:
                    pass

            # 4. Emotion context
            emotion_context = getattr(self.intent_dispatcher, "current_emotion", None)

            # 5. Intent dispatch (NLU via spaCy semantic similarity)
            _t_intent = time.monotonic()
            if _dlog:
                _dlog.log_input("NLU", f"text=\"{sanitized_text}\", emotion={emotion_context}")
            intent_payload = self.intent_dispatcher.dispatch(sanitized_text, emotion=emotion_context)
            if _dlog:
                _dlog.log_output(
                    "NLU",
                    f"intent={intent_payload.get('intent_name', '?')} conf={intent_payload.get('confidence', 0):.3f}",
                    elapsed_ms=(time.monotonic() - _t_intent) * 1000,
                )

            # 6. Emotion reactor — crisis detection (#EPIC-005 CA#1)
            _t_reactor = time.monotonic()
            if _dlog:
                _dlog.log_input("EMOTION_REACTOR", f"emotion={emotion_context}, intent={intent_payload.get('intent_name')}")
            intent_payload = self.emotion_reactor.evaluate(emotion_context, intent_payload)
            is_crisis = intent_payload.get("is_crisis", False)
            if _dlog:
                _dlog.log_output("EMOTION_REACTOR", f"is_crisis={is_crisis}", elapsed_ms=(time.monotonic() - _t_reactor) * 1000)

            # 7. Game engine — multi-turn games (#EPIC-006)
            if self.game_engine is not None:
                intent_payload = self.game_engine.process_or_passthrough(sanitized_text, intent_payload)

            # 8. Routine acknowledgment (#EPIC-007)
            intent_name = intent_payload.get("intent_name", "")
            if intent_name == "routine_ack" and self.routine_scheduler is not None:
                try:
                    ack_msg = self.routine_scheduler.acknowledge_routine("any")
                    if ack_msg:
                        intent_payload["response"] = ack_msg
                except Exception:
                    pass

            # 8.5. Fallback LLM — generate empathetic response for unknown intents
            intent_name = intent_payload.get("intent_name", "")
            if intent_name == "unknown" and self.cloud_mode and self.cloud_llm is not None and self.cloud_llm.is_available:
                _t_llm = time.monotonic()
                if _dlog:
                    _dlog.log_input("LLM_FALLBACK", f'text="{sanitized_text}" [CLOUD]')
                llm_response = self.cloud_llm.generate(sanitized_text, emotion_context)
                if llm_response:
                    intent_payload["intent_name"] = "llm_fallback"
                    intent_payload["response"] = llm_response
                    intent_payload["pilar"] = "general"
                if _dlog:
                    _dlog.log_output(
                        "LLM_FALLBACK",
                        f'response="{llm_response}"' if llm_response else "sin respuesta",
                        elapsed_ms=(time.monotonic() - _t_llm) * 1000,
                    )
            elif intent_name == "unknown" and self.fallback_llm is not None and self.fallback_llm.is_available:
                _t_llm = time.monotonic()
                if _dlog:
                    _dlog.log_input("LLM_FALLBACK", f"text=\"{sanitized_text}\"")
                llm_response = self.fallback_llm.generate(sanitized_text, emotion_context)
                if llm_response:
                    intent_payload["intent_name"] = "llm_fallback"
                    intent_payload["response"] = llm_response
                    intent_payload["pilar"] = "general"
                if _dlog:
                    _dlog.log_output(
                        "LLM_FALLBACK",
                        f"response=\"{llm_response}\"" if llm_response else "sin respuesta",
                        elapsed_ms=(time.monotonic() - _t_llm) * 1000,
                    )

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
                    if new_words and self.vocabulary_tracker is not None:
                        stats = self.vocabulary_tracker.get_stats()
                        self.telemetry.log_vocabulary_update(
                            new_words=new_words,
                            total_words=stats.get("total_words", 0),
                        )
                except Exception:
                    pass

            # 12. TTS — speak the response and block until playback finishes.
            response_text = str(intent_payload.get("response", "")).strip()
            # Truncar respuestas largas a ~25 palabras para mantener TTS < 4s.
            # Respuestas de 50+ palabras causaban 10-13s de síntesis.
            response_text = self._truncate_response(response_text, max_words=25)
            if response_text and self.speech_worker is not None:
                _t_tts = time.monotonic()
                if _dlog:
                    _dlog.log_input("TTS", f"text=\"{response_text}\"")
                self.speech_worker.speak_and_wait(response_text)
                if _dlog:
                    _dlog.log_output("TTS", "Reproducción completada", elapsed_ms=(time.monotonic() - _t_tts) * 1000)

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


    # Contextual prompt that primes Whisper for Argentine Spanish.
    # Neutral prompt — avoids biasing towards toddler vocabulary which caused
    # hallucinations (e.g. injecting "mamá" into adult speech).  Uses common
    # Argentine expressions to condition the decoder for rioplatense accent.
    _WHISPER_INITIAL_PROMPT: str = (
        "Hola, buen día. ¿Cómo estás? Quiero jugar. "
        "Sí, dale. No quiero. Dame eso. Mirá, vení. "
        "Está bueno. Vamos a hacer algo divertido."
    )

    def _load_whisper_model(self):
        _dlog = get_debug_logger()
        if _dlog:
            _dlog.log_input("WHISPER", "Cargando modelo medium (int8)...")
        _t0 = time.monotonic()
        try:
            from faster_whisper import WhisperModel

            # 'medium' model: ~1.5GB RAM (int8) — 769M params, 10x more than
            # 'base' (74M) and 3x more than 'small' (244M).  Best accuracy for
            # Spanish vocabulary including uncommon words ("flamenco", "soleado").
            # The 'small' model still garbled these as "lo amenco", "acasio", etc.
            # Fits on RPi 5 with 8GB RAM.  Slower than small but combined with
            # beam_size=1 keeps transcription in a usable range.
            model = WhisperModel("medium", device="cpu", compute_type="int8")
            if _dlog:
                _dlog.log_output("WHISPER", "Modelo cargado", elapsed_ms=(time.monotonic() - _t0) * 1000)
            return model
        except Exception:
            if _dlog:
                _dlog.log_output("WHISPER", "ERROR: No se pudo cargar")
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

        # 5. Normalize — consistent level (necesario para Whisper)
        audio = self._normalize_audio(audio)
        # 6. Pad — minimum duration for Whisper
        audio = self._pad_audio(audio, sample_rate=16000, min_duration_s=1.5)
        return audio

    def _transcribe(self, whisper_model: Any, audio_segment: np.ndarray) -> str:
        if whisper_model is None:
            return ""

        _dlog = get_debug_logger()

        # Early exit: if the raw audio is essentially silence at capture,
        # skip all processing and Whisper entirely.  This catches segments
        # where the VAD triggered on electrical noise but the mic captured
        # nothing meaningful.  We check BEFORE preprocessing because our
        # noise gate can sometimes attenuate quiet speech too aggressively.
        raw_rms = float(np.sqrt(np.mean(audio_segment ** 2)))
        if raw_rms < 0.005:
            return ""

        # Guardar copia del audio crudo ANTES del pipeline de procesamiento
        # para debug (solo si modo debug está activo)
        raw_audio_copy = audio_segment.copy() if _dlog else None

        # Full audio preprocessing pipeline:
        # bandpass → spectral denoise → noise gate → pre-emphasis → normalize → pad
        audio_segment = self._preprocess_audio(audio_segment)

        # Guardar copia del audio procesado DESPUÉS del pipeline (pre-Whisper)
        processed_audio_copy = audio_segment.copy() if _dlog else None

        segments, _info = whisper_model.transcribe(
            audio_segment,
            language="es",
            # Whisper's internal VAD pre-filters silent chunks before decoding,
            # reducing hallucinations on residual silence within segments.
            vad_filter=True,
            # Greedy decoding (beam_size=1) is 2-4x faster and produces fewer
            # hallucinations for clear adult speech.  beam_size=5 was causing
            # low-confidence hypotheses biased by the initial_prompt to win.
            beam_size=1,
            # Neutral contextual prompt for Argentine Spanish
            initial_prompt=self._WHISPER_INITIAL_PROMPT,
            # Reject hallucinations on noise/silence — raised from 0.7 to 0.75
            # to be more aggressive in noisy environments after spectral cleanup
            no_speech_threshold=0.75,
            # Log-prob threshold: -0.5 was too strict with larger models,
            # causing valid speech to be rejected as empty strings.
            # -0.8 is a balanced compromise — rejects clear garbage but
            # accepts legitimate low-confidence transcriptions.
            log_prob_threshold=-0.8,
            # Reject repetitive hallucinations ("ruido ruido ruido...")
            # caused by stationary noise feeding the decoder in a loop.
            compression_ratio_threshold=2.0,
            # Prevent previous transcription errors from biasing the next
            # segment — critical in noisy environments where one bad
            # transcription can cascade into many.
            condition_on_previous_text=False,
            # Skip timestamp prediction — saves decoder compute and lets it
            # focus entirely on text accuracy for short segments
            without_timestamps=True,
        )
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        transcript = " ".join(part for part in text_parts if part).strip()

        # Guardar audios de debug (crudo + procesado + transcripción)
        if _dlog and raw_audio_copy is not None and processed_audio_copy is not None:
            _dlog.save_debug_audio(
                raw_audio=raw_audio_copy,
                processed_audio=processed_audio_copy,
                transcript_text=transcript,
                sample_rate=16000,
            )

        return transcript

    def _load_vad(self, sample_rate: int):
        return SileroVadAdapter(sample_rate=sample_rate)


class SpeechWorker:
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

        # Cloud mode (#CLOUD-001)
        self._cloud_mode = cloud_mode
        self._cloud_tts = cloud_tts

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="SpeechWorker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait("")
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def speak(self, text: str) -> None:
        speech_text = (text or "").strip()
        if not speech_text:
            return
        try:
            self._queue.put_nowait(speech_text)
        except queue.Full:
            pass

    def set_output_device(self, output_device_index: int | None) -> None:
        self._output_device_index = output_device_index

    def speak_and_wait(self, text: str, timeout: float = 30.0) -> None:
        """Queue text for speaking and block until playback finishes."""
        speech_text = (text or "").strip()
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

    def _find_supported_samplerate(self, sample_rate: int, channels: int) -> int:
        """Return the requested sample_rate if the device supports it, otherwise
        find the best ALSA-compatible alternative.  Falls back to 48000 Hz."""
        candidates = [sample_rate, 48000, 44100, 22050, 16000, 8000]
        for sr in candidates:
            try:
                sd.check_output_settings(
                    device=self._output_device_index,
                    samplerate=float(sr),
                    channels=channels,
                    dtype="float32",
                )
                return sr
            except Exception:
                continue
        # Ultimate fallback — let PortAudio pick its default
        return 48000

    def _play_wav_via_output_stream(self, audio_array: np.ndarray, sample_rate: int) -> None:
        """Play audio using a dedicated OutputStream to avoid conflicts with AudioWorker's InputStream.

        sd.play() uses the *default* PortAudio output stream which can collide
        with an already-open InputStream on some backends.  Opening our own
        OutputStream with an explicit device avoids this.

        If the requested sample_rate is not supported by the output device
        (common on Raspberry Pi ALSA where only 48000/44100 are valid), the
        audio is resampled to a compatible rate using numpy interpolation."""
        if audio_array.ndim == 1:
            audio_array = audio_array.reshape(-1, 1)
        # Normalise int types to float32 for OutputStream compatibility
        if audio_array.dtype != np.float32:
            info = np.iinfo(audio_array.dtype)
            audio_array = audio_array.astype(np.float32) / float(info.max)

        channels = audio_array.shape[1] if audio_array.ndim > 1 else 1

        # --- Resample if the device does not support the original rate ---
        device_sr = self._find_supported_samplerate(sample_rate, channels)
        if device_sr != sample_rate:
            self._log(f"Resampleando audio de {sample_rate} Hz → {device_sr} Hz (compatibilidad ALSA)")
            audio_array = self._resample_audio(audio_array, sample_rate, device_sr)
            sample_rate = device_sr

        finished = threading.Event()
        pos = [0]  # mutable counter shared with callback

        def _callback(outdata: np.ndarray, frames: int, _time_info: Any, _status: Any) -> None:
            start = pos[0]
            end = start + frames
            chunk = audio_array[start:end]
            if len(chunk) < frames:
                outdata[:len(chunk)] = chunk
                outdata[len(chunk):] = 0
                finished.set()
                raise sd.CallbackStop()
            else:
                outdata[:] = chunk
            pos[0] = end

        with sd.OutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            device=self._output_device_index,
            callback=_callback,
        ):
            finished.wait(timeout=len(audio_array) / sample_rate + 5.0)

    def _run(self) -> None:
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
        model_name = "es_MX-ald-medium"
        cache_dir = Path.home() / ".edge_ai_models" / "piper"
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_file = cache_dir / f"{model_name}.onnx"
        config_file = cache_dir / f"{model_name}.onnx.json"

        if model_file.exists() and config_file.exists():
            return model_file

        base_url = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"es/es_MX/ald/medium/{model_name}"
        )

        for suffix, target in [(".onnx", model_file), (".onnx.json", config_file)]:
            if not target.exists():
                urllib.request.urlretrieve(f"{base_url}{suffix}", target)

        return model_file

    def _speak_piper(self, text: str) -> None:
        """Synthesize speech with piper neural TTS v1.4+ -> direct float32 -> sounddevice."""
        audio_chunks: list[np.ndarray] = []
        sample_rate: int = 22050  # default; updated from first chunk

        for chunk in self._piper_voice.synthesize(text):
            audio_chunks.append(chunk.audio_float_array)
            sample_rate = chunk.sample_rate

        if not audio_chunks:
            self._log("Piper no generó audio para el texto dado")
            return

        audio_array = np.concatenate(audio_chunks).astype(np.float32)
        # audio_float_array is already in [-1.0, 1.0] range
        self._play_wav_via_output_stream(audio_array, sample_rate)

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
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._mode = "energy"
        self._model = None
        self._get_speech_timestamps = None
        self._load()

    def _load(self) -> None:
        try:
            from silero_vad import get_speech_timestamps, load_silero_vad

            self._model = load_silero_vad()
            self._get_speech_timestamps = get_speech_timestamps
            self._mode = "silero"
        except Exception:
            self._mode = "energy"

    def has_speech(self, audio_block: np.ndarray) -> bool:
        if self._mode == "silero" and self._model is not None and self._get_speech_timestamps is not None:
            try:
                tensor_block = self._to_tensor(audio_block)
                timestamps = self._get_speech_timestamps(tensor_block, self._model, sampling_rate=self.sample_rate)
                return len(timestamps) > 0
            except Exception:
                return self._energy_fallback(audio_block)
        return self._energy_fallback(audio_block)

    @staticmethod
    def _energy_fallback(audio_block: np.ndarray) -> bool:
        if audio_block.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(audio_block), dtype=np.float32)))
        return rms > 0.01

    @staticmethod
    def _to_tensor(audio_block: np.ndarray):
        try:
            import torch

            return torch.from_numpy(np.asarray(audio_block, dtype=np.float32))
        except Exception:
            return np.asarray(audio_block, dtype=np.float32)