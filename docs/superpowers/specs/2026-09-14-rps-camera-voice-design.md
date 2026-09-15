# Piedra-papel-tijera por cámara y voz — diseño

Fecha: 2026-09-14  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

El juego `piedra_papel_tijera` ya existe en `GameEngine`: tras «¡Uno, dos, tres!» solo acepta la jugada por **STT**. El nene que muestra la mano no cuenta. La cámara hoy mira emoción facial (MediaPipe Face), no la mano.

## Objetivo

1. En una ronda de PPT, reconocer **gesto de mano** (piedra / papel / tijera) con MediaPipe Hands **en la Pi**.
2. Si el gesto es **seguro**, esa es la jugada. La voz de esa ronda **no** pisa el gesto.
3. Si **nunca** hubo gesto seguro en la ronda, vale la voz (flujo actual, con corrección `tiguera` → tijera).
4. Si no hay gesto seguro ni palabra: pedir «mostrame la mano o decime piedra, papel o tijera» y reintentar **una** vez. No suma ronda.
5. Teo **no** anuncia lo que entendió del nene; va directo a «Yo elegí X» + resultado, como hoy.
6. En `--debug`, ver en vivo la hipótesis del modelo **igual que la emoción**: overlay en el video, barra de estado y log.

## Fuera de alcance (v1)

- Overlay de mano en la LCD / modo ojos.
- Mandar frames a la PC para clasificar.
- Heurística OpenCV sin Hands.
- Que Teo «muestre» su jugada con servos o sprites.
- Veo veo u otros juegos.
- Cambiar máximos de rondas, frases de gane/empate, o keywords de inicio (`play_piedra_papel`).
- Salir del juego por gesto (sigue solo voz: basta, chau, etc.).

## Decisiones

- **Enfoque A:** Hands on-device, **solo** mientras `GameEngine.game_type == "piedra_papel_tijera"` y la sesión está en `waiting_choice`. Fuera de eso, Hands apagado.
- **Prioridad:** gesto seguro gana. Voz solo si en esa ronda no se marcó ningún gesto seguro.
- **Confirmación:** silenciosa. El nene no oye «vi papel».
- **Reintento:** 1. El segundo vacío usa el copy actual «No entendí tu elección…».
- **Hands no carga:** el juego sigue **solo por voz**. Debug: `Jugada: no disponible`.
- **Cámara:** misma de hoy (320×240, ~5 fps). No se sube la resolución en v1.

## Flujo de ronda

```
start_game / fin de ronda anterior
  → TTS «¿Listo? ¡Uno, dos, tres!»
  → waiting_choice + Hands ON
        ├─ confident_gesture (3 frames seguidos misma label)
        │     → process_choice(label); ignorar STT de la ronda
        ├─ STT con piedra|papel|tijera y nunca hubo gesto seguro
        │     → process_choice(stt)
        ├─ STT de salida (basta, chau, …)
        │     → end_game (voz siempre gana para salir)
        └─ silencio / gesto inseguro / STT sin choice
              → 1er vacío: pedir mano o voz + «uno, dos, tres»
              → 2º vacío: «No entendí tu elección…»
  → «Yo elegí {robot}. {frase}» [+ otra ronda o resumen]
  → Hands OFF si el juego terminó; si hay otra ronda, Hands sigue en waiting_choice
```

`process_choice` es el cuerpo actual de `PiedraPapelTijeraSession.process_input` **después** de parsear la label: random del robot, `_resolve`, contadores, TTS.

## Unidades

### `rps_hand.py` (lógica pura)

| | |
|---|---|
| Hace | De 21 landmarks MediaPipe → `piedra` \| `papel` \| `tijera` \| `None`, más un score 0–1 |
| Uso | `classify_rps_landmarks(points) -> RpsGuess` |
| Depende | Nada de GPIO, cámara ni `workers` |

Reglas (landmarks de una mano, coords normalizadas):

- **Tijera:** índice y medio extendidos; anular y meñique flexionados.
- **Papel:** índice, medio, anular y meñique extendidos.
- **Piedra:** esos cuatro flexionados (puño).
- **None:** menos de 21 puntos, dos manos sin elegir, o el patrón no encaja.

«Extendido» = punta del dedo más lejos de la muñeca que la articulación PIP, con margen. El `score` es el mínimo de esos márgenes (0–1). **Seguro** si `score >= 0.65`.

### `RpsGestureGate` (mismo módulo o junto al session)

Acumula guesses por frame en la ronda:

- `observe(label, score)` 
- `confident_choice()` → label si **3 frames seguidos** con la misma label y `score >= 0.65`; si no, `None`
- `reset_round()` al abrir waiting_choice y al cerrar la jugada
- `saw_confident` (bool) para que el STT sepa si debe ignorarse

A 5 fps, 3 frames ≈ 0,6 s de gesto estable. Un frame suelto no cierra.

### `CameraWorker`

- Flag `rps_hands_enabled` (set/clear desde `AudioWorker` cuando el GameEngine entra/sale de PPT `waiting_choice`).
- Con el flag on: correr Hand Landmarker (MediaPipe Tasks, un modelo en `~/.edge_ai_models/mediapipe`, download la primera vez como el face landmarker).
- Cada frame: clasificar, `gate.observe`, push frame.
- **Debug:** anotar landmarks en el frame (como el mesh de cara) y encolar:
  - `status` con `rps_gesture`: `"papel (0.82)"` o `"ninguna"` o `"no disponible"`
  - `rps_gesture` `{label, score, confident}` cuando cambia la hipótesis visible (misma cadencia que emoción: al cambiar label o cada 3 s)
- Con el flag off: no instanciar/correr Hands (CPU). Emoción facial igual que hoy si aplica.
- Si el modelo no carga: flag interno `hands_unavailable`; no crashear.

### `AudioWorker` + `PiedraPapelTijeraSession`

- Tras el TTS de «uno, dos, tres», activar Hands y `reset_round`.
- El gesto llega por la misma `message_queue` que la emoción (`kind=rps_gesture`). `AudioWorker` (o el loop que ya consume esa cola en el worker) si `confident` y sigue `waiting_choice`, llama `process_choice` **sin esperar** a que termine un utterance. Se drena el mic de esa ronda. El TTS del resultado sí se dice.
- STT en `waiting_choice`:
  - salida del juego → `process_input` actual
  - choice y `saw_confident` → descartar STT
  - choice y no `saw_confident` → `process_input` actual
  - vacío → reintento según arriba
- Extra_words STT (`piedra`, `papel`, `tijera`) se mantienen.

### Debug UI (`app.py` modo `--debug`)

Reusar el canal `status` que hoy pone `Estado detectado: feliz (0.xx)`:

- `Estado detectado: …` no se toca.
- Añadir `Jugada: papel (0.82)` (o `ninguna` / `no disponible`) cuando el payload trae `rps_gesture`.
- El panel de video muestra el frame ya anotado (mano).
- Log: `gesto=papel (0.82)` en cambios, paralelo a `emoción=…`.
- Modo ojos/LCD: no overlay, no texto de jugada en la cara.

## Errores

| Caso | Efecto |
|---|---|
| Hands no instalado / modelo ausente | Solo voz; debug `Jugada: no disponible` |
| Mano fuera de cuadro / score bajo | No confirma; pide mostrar o decir |
| Dos manos | Se usa la de **mayor score**; si ambas inseguras, None |
| PPT no activo | Hands off |
| Gesto y voz distintos en la misma ronda | Gesto, si ya fue confident; si el gesto llegó **después** de haber cerrado por voz, no se reabre la ronda |

Cierre por voz y gesto casi juntos: gana **el primero que cierre** `waiting_choice`. El gate `saw_confident` evita que un STT tardío pise un gesto que ya ganó. Un gesto tardío **no** pisa una ronda ya cerrada por voz.

## Tests (Windows, sin cámara)

- `classify_rps_landmarks`: puño, palma, tijera, 0 puntos, patrón mixto → None.
- `RpsGestureGate`: 2 frames no cierran; 3 iguales sí; un frame distinto reinicia la racha.
- Session: `process_choice("papel")` equivale a `process_input("papel")` en resultado; vacío no incrementa `rounds_played`; `basta` termina.
- Prioridad: si `saw_confident`, un texto `"piedra"` no cambia la choice ya fijada (API de ronda: `commit_choice` una vez).
- CameraWorker (test de fuente o flag): con PPT inactivo no pide Hands.

No se exige test de MediaPipe real en Windows (mock del landmarker).

## Arquitectura

```
GameEngine PPT waiting_choice
    → AudioWorker.enable_rps_hands(True)
    → CameraWorker HandLandmarker + rps_hand.classify
          → frame anotado (debug)
          → status / rps_gesture
    → AudioWorker
          ├─ confident → commit_choice(label) → TTS resultado
          └─ STT → exit | choice si !saw_confident | retry
```
