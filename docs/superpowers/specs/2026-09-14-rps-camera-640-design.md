# Captura de cámara 640×480 (PPT Hands) — diseño

Fecha: 2026-09-14  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación (opción 2); sin commit hasta que Teo lo pida  
Sustituye: en `2026-09-14-rps-camera-voice-design.md`, la decisión «Cámara 320×240, no subir en v1»

## Problema

MediaPipe Hands (modo IMAGE, det=0.20) ve bien **papel** (palma). En logs de Pi no aparecen `piedra` ni `tijera`. Un puño o una V a 320×240 es un blob chico para el palm detector.

## Objetivo

Pedir a OpenCV **640×480 al abrir la cámara**, para todo el `CameraWorker` (emoción, preview debug y Hands). Más píxeles para el detector sin cambiar de clasificador ni de modo Hands.

Si después de esto el log sigue sin `piedra`/`tijera`, el siguiente paso es silueta OpenCV (enfoque B). **No entra en este cambio.**

## Fuera de alcance

- Cambiar resolución al entrar/salir de PPT.
- Downsample a 320 para emoción.
- Gesture Recognizer, clasificador nuevo, contornos OpenCV.
- LCD / ojos (siguen 320×240).
- `frame_rate` (sigue 5).
- Reabrir o recrear `VideoCapture`.

## Decisiones

- **Enfoque 2:** un `set` al abrir: ancho 640, alto 480. No hay segundo `set` en el loop.
- Constantes: `CAMERA_CAPTURE_WIDTH = 640`, `CAMERA_CAPTURE_HEIGHT = 480` junto a la captura (no magia 320/240).
- Tras el `set`, leer `CAP_PROP_FRAME_WIDTH/HEIGHT` y loguear el tamaño **real** (la cam V4L2 a veces ignora el pedido). Si no es 640×480, no se aborta: se sigue con lo que dio el driver.
- Hands, Face y overlay de `--debug` usan el mismo frame (el que salga de `read()`).
- Tests Windows: helper o constantes, sin cámara física. Un fake `VideoCapture` que recuerde width/height basta.

## Unidades

### Apertura de captura (`CameraWorker._run`)

| | |
|---|---|
| Hace | Abre el índice, pide 640×480, loguea tamaño real |
| Uso | Una vez por vida del worker |
| Depende | OpenCV `VideoCapture` |

No se toca `rps_hand.classify_rps_landmarks` ni el HandLandmarker IMAGE.

## Tests (Windows)

- Constantes de captura = 640 y 480.
- Helper (si se extrae): `set` + `get` en un fake; el valor pedido se refleja; si el fake ignora el `set`, el log/retorno es el tamaño del fake, no un crash.

No se exige test con webcam real.

## Cómo saber si sirvió (en la Pi)

Tras reiniciar `app.py`:

1. Log al arrancar: captura ~640×480 (o el tamaño real).
2. En una ronda de PPT, puño y V: deben aparecer `gesto=piedra` / `gesto=tijera` (no solo `papel`/`ninguna`).

Si el tamaño es 640 y **igual** no hay piedra/tijera → C no alcanzó; siguiente es B.
