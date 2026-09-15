# PPT cámara + voz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline; Teo pidió implementar y subir en esta sesión).

**Goal:** En piedra-papel-tijera, la Pi reconoce el gesto de la mano; si no hay gesto seguro, usa la voz. En `--debug` se ve la hipótesis como la emoción.

**Architecture:** `rps_hand.py` clasifica landmarks y acumula frames. `CameraWorker` corre Hand Landmarker solo con PPT en `waiting_choice`. `AudioWorker` cierra la ronda si el gate está confident; si no, el STT actual. Debug reusa `status` + overlay.

**Tech Stack:** Python, MediaPipe Tasks HandLandmarker, OpenCV, GameEngine existente.

## Global Constraints

- Hands solo con `game_type == piedra_papel_tijera` y `waiting_choice`.
- Gesto seguro: `score >= 0.65` y 3 frames seguidos. Gesto gana a la voz.
- Teo no dice «vi papel». 1 reintento «Mostrame la mano…»; el 2.º «No entendí…».
- Sin commit git salvo que Teo lo pida. Subir a la Pi. No arrancar `app.py`.

---

### Task 1: `rps_hand.py`

**Files:** Create `ProyectoParaRasperrypiV5/rps_hand.py`, `ProyectoParaRasperrypiV5/test_rps_hand.py`

- [ ] Tests clasificador + gate (RED)
- [ ] Implementar `RpsGuess`, `classify_rps_landmarks`, `RpsGestureGate`
- [ ] Tests GREEN

### Task 2: GameEngine `process_choice` + reintento

**Files:** Modify `game_engine.py`, tests en `test_rps_hand.py` / `test_full.py`

- [ ] Tests: choice por label, 1.er vacío pide mano, 2.º No entendí, basta, commit una vez
- [ ] Implementar
- [ ] GREEN

### Task 3: CameraWorker Hands + debug status

**Files:** Modify `workers.py` CameraWorker, `test_camera_emotion.py`

- [ ] Flag default off; Hands no corre si off
- [ ] Landmarker lazy, overlay, `status.rps_gesture` y `kind=rps_gesture`

### Task 4: AudioWorker cierra ronda por gesto

**Files:** Modify `workers.py` AudioWorker, `app.py` (pasar `camera_worker`)

- [ ] Poll gate en `listen_until_cut`; `commit_choice`; skip STT solapado
- [ ] STT: si `saw_confident` y no es exit, descartar choice

### Task 5: Debug UI

**Files:** Modify `app.py` EdgeAiDesktopApp

- [ ] `Jugada: …` en la barra; log `gesto=`

### Task 6: Subir a la Pi

- [ ] SFTP de py tocados. Avisar reinicio de `app.py`.
