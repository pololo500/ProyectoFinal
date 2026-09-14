# Arranque peluche: dispositivos fijos, LCD, emoción 5 fps

Fecha: 2026-09-13  
Producto: `ProyectoParaRasperrypiV5/`  
Estado: aprobado en conversación

## Objetivo

Sin `--debug`, TEO arranca sin ventana HDMI: ojos solo en la LCD ST7789, con mic USB PnP, parlante Audio Advantage MicroII, Cámara 0, procesamiento Local, y emoción MediaPipe a 5 fps.

Con `--debug`, los desplegables marcan esa misma config (se puede cambiar).

## Dispositivos (match por nombre, no por hw:N,0)

- Cámara: label que contiene `Cámara 0`
- Mic: `USB PnP Sound Device`
- Parlante: `Audio Advantage MicroII`
- Modo: `local` (no Groq). El servidor PC STT/LLM sigue igual.

Si no hay match: primer dispositivo real + log.

## Arranque

- Default: `HeadlessEyeApp` (aunque haya DISPLAY/HDMI).
- `--debug`: panel actual, combos preseleccionados.
- `--gui`: ventana de ojos HDMI (opcional).

## Cámara

- `skip_camera=False`, índice 0 si hay match.
- `CameraWorker.frame_rate = 5`
- `CameraWorker.infer_emotion = True`
- Resolución 320×240 (sin cambio).
