# PPT silueta OpenCV + captura al máximo — diseño

Fecha: 2026-09-14  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: Teo pidió implementar B; CPU no era el cuello (cores < 50%). Sin commit hasta que lo pida.

## Problema

Hands (IMAGE, 640×480) ve **papel**. Puño casi nunca. Tijera aparece 1 frame a 0.66 y se pierde; el gate pide 3 seguidos ≥ 0.65. El palm detector no engancha puño/V.

## Objetivo

1. **B:** si Hands no da label, clasificar por **silueta OpenCV** (convexity defects) en el mismo frame.
2. Pedir a la cámara **el máximo** que acepte el driver (probe grande + MJPG si existe). Loguear el tamaño real.

## Fuera de alcance

- Gesture Recognizer de MediaPipe.
- Bajar `CONFIDENT_SCORE` / `STREAK_NEEDED` (el gate sigue igual; la silueta manda score 0.80).
- LCD / ojos.
- Cambiar `frame_rate`.

## Decisiones

- Hands gana si `label` no es `None`. Si no, silueta.
- Silueta: máscara de piel YCrCb → contorno más grande → defects con profundidad y ángulo &lt; 90°. Dedos = valleys+1 (0 valleys = 0 dedos).
- Mapeo: 0–1 → piedra; 2–3 → tijera; 4–5 → papel. Si no hay contorno usable → None.
- Debug: overlay `Jugada: piedra sil (0.80)` y contorno; log `gesto=piedra` igual que Hands (el gate no cambia).
- Captura: FOURCC MJPG si se puede, luego `set` 10000×10000 y leer `CAP_PROP` real. Si el driver ignora, se sigue con lo que dio.

## Tests (Windows)

- `classify_rps_finger_count` y merge Hands-primero.
- Conteo de valleys con geometría sintética (sin webcam).
- Probe de captura: fake que clampa a 1920×1080; fake que ignora el `set`.
- `_process_hands_frame` sin landmarks usa silueta (patch).
