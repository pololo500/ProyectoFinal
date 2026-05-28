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
        return []
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
        try:
            return spacy.load("es_core_news_sm")
        except Exception:
            return spacy.blank("es")

    def dispatch(self, text: str, emotion: dict[str, Any] | None = None) -> dict[str, Any]:
        candidate_text = (text or "").strip()
        if not candidate_text:
            return {"intent_name": "unknown", "confidence": 0.0, "response": ""}

        source_doc = self.nlp(candidate_text)
        best_match = {"intent_name": "unknown", "confidence": 0.0, "response": ""}

        # Use provided emotion context or the last observed one
        emotion_context = emotion if emotion is not None else self.current_emotion

        for intent_name, intent_definition in self.intents.items():
            examples = intent_definition.get("examples", [])
            response = intent_definition.get("response", "")
            required_emotions = intent_definition.get("emotions")
            emotion_threshold = float(intent_definition.get("emotion_threshold", 0.0))
            for example in examples:
                similarity = self._similarity(source_doc, self.nlp(example))
                # If the intent defines required emotions, ensure the current
                # emotion matches at least one (OR logic) and meets the threshold.
                if required_emotions:
                    if not emotion_context:
                        # no emotion info -> skip this intent
                        continue
                    label = str(emotion_context.get("label", "")).lower()
                    score = float(emotion_context.get("score", 0.0))
                    matches_emotion = any(label == req.lower() and score >= emotion_threshold for req in required_emotions)
                    if not matches_emotion:
                        continue

                if similarity > best_match["confidence"]:
                    best_match = {
                        "intent_name": intent_name,
                        "confidence": float(similarity),
                        "response": response,
                    }

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
    def sanitize(self, text: str) -> dict[str, Any]:
        original_text = text or ""
        findings: list[dict[str, Any]] = []
        sanitized_text = original_text
        replacement_terms: list[str] = []

        try:
            import scrubadub

            scrubber = scrubadub.Scrubber()
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
        self._thread: threading.Thread | None = None
        # Capture at a reduced frame rate to lower CPU usage (frames per second)
        self.frame_rate = 5

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
            capture_backend = getattr(cv2, "CAP_DSHOW", 0)
            capture = cv2.VideoCapture(self.camera_index, capture_backend)
            if not capture.isOpened():
                raise RuntimeError(f"No se pudo abrir la cámara {self.camera_index}")

            # Ruta clasica de MediaPipe (API solutions).
            if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):
                mp_face_mesh = mp.solutions.face_mesh
                mp_drawing = mp.solutions.drawing_utils
                drawing_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1)
                connection_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1)
                face_mesh = mp_face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                face_mesh_enabled = True
                _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", "MediaPipe FaceMesh habilitado")
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
                f"Estado: cámara {self.camera_index} activa",
            )
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
                        if (now - last_emotion_log_ts) >= 1.0 or emotion_label != last_emotion_label:
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
                                f"Estado: cámara {self.camera_index} activa | emoción: {emotion_label} ({emotion_score:.2f})",
                            )
                            last_emotion_log_ts = now
                            last_emotion_label = emotion_label
                else:
                    self._push_frame(frame)

        except Exception as exc:
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en cámara: {exc}")
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "status", "Estado: error en cámara")
        finally:
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

        annotated = frame.copy()
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
    ) -> None:
        self.microphone_device_index = microphone_device_index
        self.message_queue = message_queue
        self.message_semaphore = message_semaphore
        self.intent_dispatcher = intent_dispatcher
        self.sanitizer = TextSanitizer()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
        silence_threshold_seconds = 2.5
        circular_buffer: deque[np.ndarray] = deque(maxlen=int(sample_rate * 10))
        current_segment: list[np.ndarray] = []
        silence_seconds = 0.0
        speech_active = False

        whisper_model = self._load_whisper_model()
        vad = self._load_vad(sample_rate)
        audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)

        def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            if status:
                _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Audio callback: {status}")
            try:
                audio_block = np.copy(indata[:, 0]).astype(np.float32)
                audio_queue.put_nowait(audio_block)
            except queue.Full:
                pass

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
                    f"Estado: micrófono {self.microphone_device_index} activo",
                )
                _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", "silero-vad: escuchando...")

                while not self._stop_event.is_set():
                    try:
                        audio_block = audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    circular_buffer.append(audio_block)
                    speech_detected = vad.has_speech(audio_block)

                    if speech_detected:
                        if not speech_active:
                            speech_active = True
                            current_segment = [audio_block]
                            _queue_message_with_semaphore(
                                self.message_queue,
                                self.message_semaphore,
                                "log",
                                "silero-vad: escuchando...",
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
                            self._handle_segment(segment_audio, whisper_model)

        except Exception as exc:
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en micrófono: {exc}")
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "status", "Estado: error en micrófono")

    def _handle_segment(self, audio_segment: np.ndarray, whisper_model: Any) -> None:
        if audio_segment.size == 0:
            return

        try:
            raw_text = self._transcribe(whisper_model, audio_segment)
            sanitized_payload = self.sanitizer.sanitize(raw_text)
            # Pass the last known emotion context to the dispatcher (if any)
            emotion_context = getattr(self.intent_dispatcher, "current_emotion", None)
            intent_payload = self.intent_dispatcher.dispatch(sanitized_payload["sanitized_text"], emotion=emotion_context)

            _queue_message_with_semaphore(
                self.message_queue,
                self.message_semaphore,
                "transcript",
                {
                    "raw_text": raw_text,
                    "sanitized": sanitized_payload,
                    "emotion": getattr(self.intent_dispatcher, "current_emotion", None),
                    "intent": intent_payload,
                },
            )
        except Exception as exc:
            _queue_message_with_semaphore(self.message_queue, self.message_semaphore, "log", f"Error en transcripción o NLU: {exc}")

    def _load_whisper_model(self):
        try:
            from faster_whisper import WhisperModel

            return WhisperModel("base", device="cpu", compute_type="int8")
        except Exception:
            return None

    def _transcribe(self, whisper_model: Any, audio_segment: np.ndarray) -> str:
        if whisper_model is None:
            return ""

        segments, _info = whisper_model.transcribe(audio_segment, language="es", vad_filter=False)
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        return " ".join(part for part in text_parts if part).strip()

    def _load_vad(self, sample_rate: int):
        return SileroVadAdapter(sample_rate=sample_rate)


class SpeechWorker:
    def __init__(self, output_device_index: int | None = None) -> None:
        self._queue: queue.Queue[str] = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_windows = sys.platform.startswith("win")
        self._output_device_index = output_device_index

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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if self._stop_event.is_set() or not text:
                continue

            if not self._is_windows:
                continue

            try:
                self._speak_windows(text)
            except Exception:
                # If TTS fails once, keep the worker alive but skip the utterance.
                continue

    def _speak_windows(self, text: str) -> None:
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_file:
            wav_path = wav_file.name

        try:
            escaped_text = saxutils.escape(text)
            script = (
                "Add-Type -AssemblyName System.Speech;"
                f"$out = '{wav_path.replace("'", "''")}';"
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

            sd.play(audio_array, samplerate=sample_rate, device=self._output_device_index)
            sd.wait()
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