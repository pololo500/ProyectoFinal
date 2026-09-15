# Hands IMAGE mode (PPT) Implementation Plan

> Teo eligió opción A. Sin commit salvo que lo pida. Subir a la Pi.

**Goal:** Que el palm detector corra **en cada frame** de PPT, con umbral más bajo, para enganchar puño y tijera sin abrir la palma antes.

**Change:** `rps_hand.py` exporta config; `CameraWorker` crea HandLandmarker en `RunningMode.IMAGE` y llama `detect()` (no `detect_for_video`). Solo mientras Hands está on (PPT `waiting_choice`).

## Task 1 — Config + detect()

- [ ] Test: config `running_mode=IMAGE`, `min_hand_detection_confidence=0.2`
- [ ] Test: `_process_hands_frame` llama `detect`, no `detect_for_video`
- [ ] Implementar
- [ ] Tests GREEN, SFTP, avisar reinicio
