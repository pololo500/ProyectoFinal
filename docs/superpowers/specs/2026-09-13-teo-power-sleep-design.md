# Estado prendido / apagado (sueño) de TEO — diseño

Fecha: 2026-09-13  
Producto: peluche TEO (`ProyectoParaRasperrypiV5` + `ProyectoAndroid`)  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

Hoy `POST /api/power` y el botón Encendido de la app existen, pero Teo **arranca prendido**, apagar **mata los workers** (y descarga los modelos) y el pulsador de panza **siempre pide un abrazo**. El tope diario solo dice “hoy ya jugamos bastante” y sigue despierto. “Chau” es una despedida enlatada, sin irse a dormir.

Hace falta un modo dormido real: modelos en RAM, API parental viva, despertar por app o por panza, y apagarse por padre, tope diario o voz del nene (con repregunta).

## Objetivo

1. Al ejecutar `app.py`, Teo empieza **apagado** (dormido). Los workers se levantan igual que hoy y cargan en RAM de la Pi todo lo que hoy se carga al prender (cámara, Vosk/Whisper, VAD, Piper, LLM local, etc.).
2. Mientras carga o duerme, el servidor parental (puerto 8080) sigue arriba.
3. Se prende por el botón Encendido de la app, o por el pulsador de panza si el chip parental lo permite.
4. Si se pide prender **antes** de que terminen los modelos: se reproduce un audio **pre-generado** (TTS Edge, un archivo en disco, cero síntesis en runtime) y el pedido **queda en cola**; al terminar la carga, se prende solo.
5. Despierto: todas las funciones actuales.
6. Se apaga por: padre en la app (inmediato), tope de juego diario, o voz del nene (chau / no quiero jugar) **solo si confirma** con un sí claro.
7. Chip en Inicio: habilita o no usar la panza para **prender**. Default **on**. No cambia el abrazo cuando ya está despierto.

## Fuera de alcance (v1)

- Apagar el proceso de `app.py` o la Pi.
- Usar la panza para apagar (despierto = abrazo).
- Timeout que duerma si el nene no responde la repregunta.
- Extra de minutos al override del padre (el contador del día vuelve a **cero**).
- Cambiar modo noche, mute de intents, o el servidor de PC.
- Animación nueva de ojos: se reusa la expresión `dormido` que ya existe.

## Decisiones

- **Gate, no teardown.** `_apply_power(False)` ya no llama a `stop_workers`. Los modelos quedan en RAM. `power_on` es un gate de conversación / cámara / rutinas / música / cuentos / celebrar.
- **Tres fases:** `loading` (apagado, modelos no listos) → `asleep` (apagado, listos) → `awake` (prendido).
- **Cola de encendido:** `pending_wake`. `/api/status.power_on` es `true` si está despierto **o** hay cola, para que el botón de la app no parpadee. El gate real de workers usa solo “despierto” (`SleepState.power_on`).
- **Panza:** despierto → abrazo. Dormido/cargando + chip on + tope no bloquea → wake o cola. Chip off o tope bloqueando → ignore.
- **Tope diario:** al cumplirse, dice `PLAYTIME_DECLINE_PHRASE` y pasa a dormido. La panza no despierta **ese día**. La app sí; al pedir prender, `PlaytimeGuard.reset_today()` (contador a 0) y se limpia el bloqueo de panza. A medianoche el bloqueo caduca aunque nadie hable.
- **Voz:** disparadores = keywords `farewell` o “no quiero jugar / no quiero jugar más / no quiero más”. Si hay juego/yoga/cuento, primero sale. Frase: `¿Querés que me vaya a dormir?`. Solo un sí **exacto** (tras normalizar) duerme. Cualquier otra cosa o silencio: se cancela la espera y el turno se procesa normal. Sin timeout de sueño.
- **Clip de carga:** generar **una vez** en Windows con Microsoft Edge TTS (`edge-tts`, voz `es-AR-ElenaNeural`), guardar PCM WAV 16-bit en `ProyectoParaRasperrypiV5/assets/todavia_no_estoy_listo.wav`, subir a la Pi. Runtime: reproducir el archivo por el output ya elegido, sin Piper/LLM. Si falta el archivo: log, no crash; la cola sigue.
- **Chip:** Inicio, debajo de Encendido, checkable, default on, persistido en la Pi (`parental_prefs.json` + `POST /api/config` con `belly_wake_enabled`).
- **Sí claro** (texto ya pasado por `_normalize` de `session_policy`): el utterance entero es uno de `si`, `sip`, `dale`, `bueno`, `ok`, `okay`, `si quiero`, `si teo`, `dale teo`, `bueno teo`.

## Arquitectura

```
app.py arranque
  → API 8080
  → workers (carga modelos) + pulsador
  → SleepState.phase = loading, ojos dormido
  → AudioWorker termina carga → mark_models_ready()
        ├─ pending_wake → awake, ojos neutral
        └─ si no → asleep, ojos dormido

POST /api/power / panza
  → SleepState.request_wake / on_belly
        ├─ loading → play WAV + pending_wake
        ├─ asleep  → power_on True
        └─ awake   → (panza = hug; app power false = sleep)

AudioWorker loop
  → si no despierto: drenar cola de mic, no STT/LLM
  → si despierto: loop actual
        └─ awaiting_sleep_confirm / farewell / playtime → SleepState
```

Unidad nueva `sleep_state.py`: lógica pura, testeable en Windows. `robot_state` la posee. `app.py` / `workers.py` / `hardware` callback solo preguntan y ejecutan efectos (ojos, WAV, hug, reset playtime).

## Unidades

### `SleepState` (`sleep_state.py`)

| | |
|---|---|
| Hace | Fases, cola, chip, bloqueo por tope, repregunta |
| Uso | `state.on_belly()`, `state.request_wake("app")`, `state.request_sleep(reason)`, `state.mark_models_ready()` |
| Depende | `datetime.date` (inyectable en tests) |

```python
Phase = Literal["loading", "asleep", "awake"]
BellyAction = Literal["hug", "wake", "queue", "ignore"]
WakeResult = Literal["woke", "queued", "blocked", "already_on"]
SleepReason = Literal["app", "playtime", "child"]
```

`status_power_on()` → `power_on or pending_wake`.

### Frases (`sleep_state.py` + `session_policy._normalize`)

- `SLEEP_CONFIRM_PHRASE = "¿Querés que me vaya a dormir?"`
- `SLEEP_GOODNIGHT_PHRASE = "Bueno, me voy a dormir."`
- `NOT_READY_TEXT = "Todavía no estoy listo, dame unos segundos más."`
- `NOT_READY_CLIP = APP_DIR / "assets" / "todavia_no_estoy_listo.wav"`
- `is_sleep_request_text(text)` — farewell keyword o regex `\bno quiero( jugar)?( mas| más)?\b`
- `is_sleep_confirm_yes(text)` — match exacto del frozenset de sí.

### `PlaytimeGuard` (`session_policy.py`)

- `reset_today()` pone `_seconds = 0` y alinea `today`.
- `is_over_limit()` / `add_seconds()` hacen rollover de día **aunque no se haya hablado** (hoy el rollover solo ocurre en `add_seconds`).

### `RobotState` / API

Campos nuevos en `to_dict()`: `models_ready`, `belly_wake_enabled`, `pending_wake`.  
`power_on` del JSON = `sleep.status_power_on()`.  
Default al construir: `SleepState()` → `power_on=False`, `belly_wake_enabled=True`.  
`POST /api/power` llama `request_wake("app")` o `request_sleep("app")`. Si el wake es de la app, también `playtime_guard.reset_today()` y se limpia el bloqueo de panza.  
`POST /api/config` acepta `belly_wake_enabled: bool` y lo persiste.  
Música / cuentos / celebrar: no-op (JSON `{"status":"ok","power_on":false}`) si no está despierto.

### Workers y app

- Arranque: ojos `dormido`; no hablar.
- `AudioWorker`: tras cargar modelos, `mark_models_ready()`. Mientras no despierto, drena el mic y no despacha. `speak` de conversación no corre.
- `SpeechWorker.play_canned_file(path)`: decodifica WAV PCM (o el decoder ya usado) **sin** marcar música ni notificar “reproduciendo canción”. Se usa para el clip de no-listo. Si el path no existe, `False`.
- `SpeechWorker.speak`: si no despierto, no encola, **salvo** `allow_when_asleep=True` (frase de tope diario y goodnight al dormirse).
- Cámara: si no despierto, no infiere emoción (sigue viva para no descargar MediaPipe).
- Rutinas: `_check_routines` no habla si no despierto.
- Panza: un solo watcher desde que hay GPIO; el callback pregunta `on_belly()`.

### Android

- Chip checkable debajo de Encendido: “Prender con el botón”.
- `robotStatus` actualiza chip y Encendido (`power_on` del status, que incluye cola).
- Toggle del chip → `POST /api/config` solo con `belly_wake_enabled` (no pisa volumen).
- Default local del chip: on, hasta que llegue status.

## Comportamiento esperado

| Evento | Resultado |
|---|---|
| Boot | loading, ojos dormido, API up, modelos cargando |
| Modelos listos, sin cola | asleep |
| Encendido o panza (chip on) en loading | WAV + cola; al listo → awake, ojos neutral |
| Panza chip off o tope del día | ignore |
| Panza despierto | abrazo |
| App apagar | asleep inmediato, sin repregunta |
| Tope diario | frase actual + asleep; panza bloqueada hasta mañana o hasta wake de app (reset 0) |
| “chau” / “no quiero jugar” | repregunta; `si` → goodnight + asleep; otra frase → turno normal |
| Falta el WAV | log; cola igual |

## Tests

`ProyectoParaRasperrypiV5/test_sleep_state.py` (unittest, Windows):

- Boot → `loading`; `mark_models_ready()` sin cola → `asleep`; con `pending_wake` → `awake`.
- Panza: hug solo en awake; wake en asleep + chip; queue en loading; ignore si chip off o bloqueo de tope.
- App wake con tope: `reset_today` + desbloquea panza (se testea en el helper que combina ambos).
- `status_power_on` true si cola aunque `power_on` interno sea false.
- `is_sleep_confirm_yes("sí")` / `"dale"` true; `"juguemos"` / `"sí pero seguí"` false.
- `is_sleep_request_text("chau")` y `"no quiero jugar más"` true; `"hola"` false.
- `PlaytimeGuard.reset_today` y rollover de `is_over_limit` al cambiar el día sin `add_seconds`.

`test_hardware.py`: el HAL no cambia el significado del GPIO; el ruteo se testea en `SleepState.on_belly`.

Android: sin test instrumentado en v1; el contrato es el JSON de status/config.

## Rollback

| Palanca | Nuevo | Anterior | Cómo volver |
|---|---|---|---|
| Default power | off | on | `SleepState(power_on=True)` y no gatear workers |
| Apagar | gate | `stop_workers()` | restaurar `_apply_power` viejo |
| Panza | wake si dormido | siempre hug | callback solo `perform_hug_ask` |
| Clip | archivo Edge TTS | no existía | omitir `play_canned_file` |
