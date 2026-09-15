"""Clasificador de piedra/papel/tijera a partir de landmarks de una mano.

Lógica pura: sin cámara, GPIO ni workers. 21 puntos MediaPipe Hands
(coords normalizadas). El pulgar no entra en el patrón.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

_INDEX_TIP, _INDEX_MCP = 8, 5
_MIDDLE_TIP, _MIDDLE_MCP = 12, 9
_RING_TIP, _RING_MCP = 16, 13
_PINKY_TIP, _PINKY_MCP = 20, 17
_WRIST = 0

# dist(punta, MCP) / palma. MediaPipe en puño deja la punta cerca del nudillo.
_FINGER_OPEN_RATIO = 0.45
_FINGER_CLOSED_RATIO = 0.35
CONFIDENT_SCORE = 0.65
STREAK_NEEDED = 3

# Palm detector en cada frame (Tasks IMAGE). Umbral bajo para puño/tijera.
RPS_HAND_RUNNING_MODE = "IMAGE"
RPS_MIN_HAND_DETECTION_CONFIDENCE = 0.2
RPS_NUM_HANDS = 2
HANDS_INFER_WIDTH = 640
HANDS_INFER_HEIGHT = 480
# MediaPipe Hands pierde contraste con poca luz; gamma < 1 aclara.
LOW_LIGHT_LUMA = 70.0
LOW_LIGHT_LUMA_FLOOR = 25.0
LOW_LIGHT_GAMMA_FLOOR = 0.50


def rps_hand_landmarker_config() -> dict[str, object]:
    """Opciones del HandLandmarker para PPT. Sin importar MediaPipe."""
    return {
        "running_mode": RPS_HAND_RUNNING_MODE,
        "min_hand_detection_confidence": RPS_MIN_HAND_DETECTION_CONFIDENCE,
        "num_hands": RPS_NUM_HANDS,
    }


def hand_inference_size(width: int, height: int) -> tuple[int, int]:
    """Hands IMAGE a 1280×720 en la Pi no detecta ni palma; inferir a 640×480."""
    if int(width) <= HANDS_INFER_WIDTH and int(height) <= HANDS_INFER_HEIGHT:
        return int(width), int(height)
    return HANDS_INFER_WIDTH, HANDS_INFER_HEIGHT


def low_light_gamma(mean_luma: float) -> float:
    """Gamma < 1 aclara. 1.0 = no tocar (luz suficiente)."""
    luma = float(mean_luma)
    if luma >= LOW_LIGHT_LUMA:
        return 1.0
    if luma <= LOW_LIGHT_LUMA_FLOOR:
        return LOW_LIGHT_GAMMA_FLOOR
    span = LOW_LIGHT_LUMA - LOW_LIGHT_LUMA_FLOOR
    t = (luma - LOW_LIGHT_LUMA_FLOOR) / span
    return LOW_LIGHT_GAMMA_FLOOR + t * (1.0 - LOW_LIGHT_GAMMA_FLOOR)


def boost_low_light_bgr(frame: Any) -> Any:
    """LUT gamma en el frame de inferencia si el brillo medio es bajo."""
    arr = np.asarray(frame, dtype=np.uint8)
    if arr.size == 0:
        return arr
    gamma = low_light_gamma(float(arr.mean()))
    if gamma >= 0.999:
        return arr
    lut = ((np.arange(256, dtype=np.float32) / 255.0) ** gamma * 255.0).clip(0, 255).astype(np.uint8)
    return lut[arr]


Point = Sequence[float]


@dataclass(frozen=True)
class RpsGuess:
    label: str | None
    score: float
    source: str = "hands"


SILHOUETTE_SCORE = 0.80


def _dist(a: Point, b: Point) -> float:
    return ((float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2) ** 0.5


def _palm_size(points: Sequence[Point]) -> float:
    return max(_dist(points[_WRIST], points[_MIDDLE_MCP]), _dist(points[_INDEX_MCP], points[_PINKY_MCP]), 1e-6)


def _finger_openness(points: Sequence[Point], mcp: int, tip: int) -> float:
    """Qué tan estirado está el dedo: punta lejos del MCP, normalizado por la palma."""
    return _dist(points[tip], points[mcp]) / _palm_size(points)


def classify_rps_landmarks(points: Sequence[Point]) -> RpsGuess:
    if len(points) < 21:
        return RpsGuess(label=None, score=0.0)

    openness = [
        _finger_openness(points, _INDEX_MCP, _INDEX_TIP),
        _finger_openness(points, _MIDDLE_MCP, _MIDDLE_TIP),
        _finger_openness(points, _RING_MCP, _RING_TIP),
        _finger_openness(points, _PINKY_MCP, _PINKY_TIP),
    ]
    is_open = [value >= _FINGER_OPEN_RATIO for value in openness]
    is_closed = [value <= _FINGER_CLOSED_RATIO for value in openness]
    n_open = sum(is_open)
    n_closed = sum(is_closed)

    if n_closed >= 3 and n_open <= 1:
        score = 0.9 if n_closed == 4 else 0.75
        return RpsGuess(label="piedra", score=score)
    if is_open[0] and is_open[1] and is_closed[2] and is_closed[3]:
        return RpsGuess(label="tijera", score=0.9)
    if is_open[0] and is_open[1] and n_open <= 3 and n_closed >= 1:
        return RpsGuess(label="tijera", score=0.75)
    if n_open >= 4:
        return RpsGuess(label="papel", score=0.9)
    return RpsGuess(label=None, score=max(openness) if openness else 0.0)


def classify_rps_finger_count(n: int | None) -> RpsGuess:
    """0–1 puño, 2–3 tijera, 4–5 papel. Sin OpenCV."""
    if n is None:
        return RpsGuess(label=None, score=0.0, source="silueta")
    if n <= 1:
        return RpsGuess(label="piedra", score=SILHOUETTE_SCORE, source="silueta")
    if n <= 3:
        return RpsGuess(label="tijera", score=SILHOUETTE_SCORE, source="silueta")
    if n <= 5:
        return RpsGuess(label="papel", score=SILHOUETTE_SCORE, source="silueta")
    return RpsGuess(label=None, score=0.0, source="silueta")


def merge_rps_guesses(hands: RpsGuess, silhouette: RpsGuess) -> RpsGuess:
    if hands.label:
        return hands
    return silhouette


def count_finger_valleys(
    starts: Sequence[Sequence[float]],
    ends: Sequence[Sequence[float]],
    fars: Sequence[Sequence[float]],
    depths: Sequence[float],
    *,
    min_depth: float,
    max_angle_deg: float = 90.0,
) -> int:
    """Valleys válidos + 1 = dedos. 0 valleys → 0 dedos (puño)."""
    valleys = 0
    for start, end, far, depth in zip(starts, ends, fars, depths):
        if float(depth) < min_depth:
            continue
        ax = float(start[0]) - float(far[0])
        ay = float(start[1]) - float(far[1])
        bx = float(end[0]) - float(far[0])
        by = float(end[1]) - float(far[1])
        a = math.hypot(ax, ay)
        b = math.hypot(bx, by)
        if a < 1e-6 or b < 1e-6:
            continue
        c = math.hypot(float(start[0]) - float(end[0]), float(start[1]) - float(end[1]))
        cosang = (a * a + b * b - c * c) / (2.0 * a * b)
        cosang = max(-1.0, min(1.0, cosang))
        angle = math.degrees(math.acos(cosang))
        if angle <= max_angle_deg:
            valleys += 1
    if valleys <= 0:
        return 0
    return min(valleys + 1, 5)


def extract_hand_silhouette(frame: Any) -> tuple[int | None, Any]:
    """Piel YCrCb + convexity defects. (dedos, contorno) o (None, None)."""
    import cv2
    import numpy as np

    if frame is None:
        return None, None
    arr = np.asarray(frame)
    if arr.ndim != 3 or arr.size == 0:
        return None, None
    height, width = arr.shape[:2]
    blur = cv2.GaussianBlur(arr, (5, 5), 0)
    ycrcb = cv2.cvtColor(blur, cv2.COLOR_BGR2YCrCb)
    lower = np.array([0, 125, 70], dtype=np.uint8)
    upper = np.array([255, 180, 135], dtype=np.uint8)
    mask = cv2.inRange(ycrcb, lower, upper)
    ksz = max(5, (min(height, width) // 80) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    found = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]
    if contours is None or len(contours) == 0:
        return None, None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < 0.015 * float(width * height):
        return None, None
    peri = float(cv2.arcLength(contour, True))
    if peri < 1.0:
        return None, None
    hull_idx = cv2.convexHull(contour, returnPoints=False)
    if hull_idx is None or len(hull_idx) < 3:
        return 0, contour
    defects = cv2.convexityDefects(contour, hull_idx)
    _x, _y, _bw, bh = cv2.boundingRect(contour)
    min_depth = max(8.0, 0.10 * float(bh))
    if defects is None:
        return 0, contour
    starts: list[tuple[float, float]] = []
    ends: list[tuple[float, float]] = []
    fars: list[tuple[float, float]] = []
    depths: list[float] = []
    for i in range(int(defects.shape[0])):
        s_i, e_i, f_i, d_i = defects[i, 0]
        starts.append((float(contour[s_i][0][0]), float(contour[s_i][0][1])))
        ends.append((float(contour[e_i][0][0]), float(contour[e_i][0][1])))
        fars.append((float(contour[f_i][0][0]), float(contour[f_i][0][1])))
        depths.append(float(d_i) / 256.0)
    fingers = count_finger_valleys(starts, ends, fars, depths, min_depth=min_depth)
    compactness = (4.0 * math.pi * area) / (peri * peri)
    if compactness >= 0.70 and fingers <= 1:
        return 0, contour
    return fingers, contour


def silhouette_rps_guess(frame: Any) -> RpsGuess:
    try:
        fingers, contour = extract_hand_silhouette(frame)
    except Exception:
        return RpsGuess(label=None, score=0.0, source="silueta")
    guess = classify_rps_finger_count(fingers)
    if contour is not None and guess.label:
        try:
            import cv2

            cv2.drawContours(frame, [contour], -1, (0, 165, 255), 2)
        except Exception:
            pass
    return guess


class RpsGestureGate:
    """Acumula guesses por frame. 3 seguidos con score alto cierran la ronda."""

    def __init__(self) -> None:
        self._streak_label: str | None = None
        self._streak_n = 0
        self.saw_confident = False
        self._confident_label: str | None = None

    def observe(self, label: str | None, score: float) -> None:
        if label is None or score < CONFIDENT_SCORE:
            self._streak_label = None
            self._streak_n = 0
            return
        if label == self._streak_label:
            self._streak_n += 1
        else:
            self._streak_label = label
            self._streak_n = 1
        if self._streak_n >= STREAK_NEEDED:
            self.saw_confident = True
            self._confident_label = label

    def confident_choice(self) -> str | None:
        return self._confident_label

    def reset_round(self) -> None:
        self._streak_label = None
        self._streak_n = 0
        self.saw_confident = False
        self._confident_label = None
