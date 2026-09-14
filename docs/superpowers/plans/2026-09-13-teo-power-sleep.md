# TEO prendido/apagado (sueño) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD. Sin `git commit` salvo pedido de Teo.

**Goal:** Teo arranca dormido con los modelos en RAM, se prende por la app o la panza, y se duerme por padre, tope diario o voz confirmada.

**Architecture:** `SleepState` puro decide fases (`loading` / `asleep` / `awake`), cola de wake, chip y bloqueo de panza. Workers siguen vivos; el gate corta STT/LLM/rutinas/música. Clip de “no estoy listo” es un WAV pre-generado con Edge TTS.

**Tech Stack:** Python 3.11, `unittest`, Android Kotlin/XML, `edge-tts` solo para generar el clip en Windows.

**Spec:** `docs/superpowers/specs/2026-09-13-teo-power-sleep-design.md`

## Global Constraints

- TDD: test rojo **antes** de producción. `python -m unittest …` desde `ProyectoParaRasperrypiV5`. **No pytest.**
- Sin commit salvo pedido de Teo (omitir todos los `git commit`).
- No matar workers al apagar. No usar la panza para apagar.
- Sí de confirmación: match **exacto** tras `_normalize`, frozenset de la spec.
- Clip: generar con `edge-tts` voz `es-AR-ElenaNeural`, PCM WAV 16-bit en `ProyectoParaRasperrypiV5/assets/todavia_no_estoy_listo.wav`. Runtime no sintetiza.
- Tras cambios de producción que corren en la Pi, subir con `uploading-to-raspberry-pi`. `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. **NUNCA** arrancar `app.py` salvo que Teo lo pida.
- PowerShell: no `&&`. Clave SSH solo en env de la invocación.

---

## File structure

- Create: `ProyectoParaRasperrypiV5/sleep_state.py` — máquina de estados y frases.
- Create: `ProyectoParaRasperrypiV5/test_sleep_state.py` — unittest del estado.
- Create: `ProyectoParaRasperrypiV5/assets/todavia_no_estoy_listo.wav` — clip Edge TTS.
- Create: `ProyectoParaRasperrypiV5/scripts/generate_not_ready_clip.py` — generador one-shot.
- Modify: `ProyectoParaRasperrypiV5/session_policy.py` — `PlaytimeGuard.reset_today` + rollover en `is_over_limit`.
- Modify: `ProyectoParaRasperrypiV5/test_session_policy.py` — tests de reset/rollover.
- Modify: `ProyectoParaRasperrypiV5/api_server.py` — defaults off, status extra, config chip, gate play/celebrate.
- Modify: `ProyectoParaRasperrypiV5/app.py` — boot dormido, `_apply_power` = gate, panza ruteada, rutinas gated.
- Modify: `ProyectoParaRasperrypiV5/workers.py` — no escuchar dormido, `mark_models_ready`, confirmación, playtime→sleep, `play_canned_file`, `speak(..., allow_when_asleep=)`.
- Modify: `ProyectoParaRasperrypiV5/test_hardware.py` — sin cambiar GPIO; cobertura de ruteo está en `test_sleep_state`.
- Modify: Android dashboard + `RobotApiClient` / `RobotConnectionManager` / strings.

---

### Task 1: `SleepState` puro

**Files:**
- Create: `ProyectoParaRasperrypiV5/sleep_state.py`
- Test: `ProyectoParaRasperrypiV5/test_sleep_state.py`

**Interfaces:**
- Consumes: `session_policy._normalize`
- Produces: `SleepState`, `is_sleep_request_text`, `is_sleep_confirm_yes`, constantes de frase

- [ ] **Step 1: Write the failing tests** (`test_sleep_state.py`) — ver implementación de referencia abajo.
- [ ] **Step 2: Run** `python -m unittest test_sleep_state.py -v` — FAIL (módulo ausente).
- [ ] **Step 3: Implement `sleep_state.py`** mínimo para verde.
- [ ] **Step 4: Re-run unittest** — PASS.
- [ ] **Step 5: No commit.**

API a implementar:

```python
SLEEP_CONFIRM_PHRASE = "¿Querés que me vaya a dormir?"
SLEEP_GOODNIGHT_PHRASE = "Bueno, me voy a dormir."
NOT_READY_TEXT = "Todavía no estoy listo, dame unos segundos más."
NOT_READY_CLIP_NAME = "todavia_no_estoy_listo.wav"

def not_ready_clip_path(app_dir: Path) -> Path:
    return app_dir / "assets" / NOT_READY_CLIP_NAME

class SleepState:
    def phase(self) -> Phase: ...
    def status_power_on(self) -> bool: ...
    def on_belly(self, today: date | None = None) -> BellyAction: ...
    def request_wake(self, source: Literal["app", "belly"], today: date | None = None) -> WakeResult: ...
    def request_sleep(self, reason: SleepReason, today: date | None = None) -> None: ...
    def mark_models_ready(self) -> bool: ...  # True si quedó awake por cola
    def set_belly_wake_enabled(self, enabled: bool) -> None: ...
    def note_parent_wake(self) -> None: ...  # limpia bloqueo de panza
```

Tests mínimos: boot loading; mark sin cola → asleep; request_wake app en loading → queued + status_power_on True + mark → awake; belly hug solo awake; belly queue en loading; ignore si chip off; ignore si playtime block mismo día; parent wake limpia block; confirm yes/no; sleep request chau / no quiero jugar.

---

### Task 2: `PlaytimeGuard.reset_today` y rollover

**Files:**
- Modify: `ProyectoParaRasperrypiV5/session_policy.py`
- Modify: `ProyectoParaRasperrypiV5/test_session_policy.py`

- [ ] Tests: `reset_today` deja `is_over_limit` False; `is_over_limit` con `today` de ayer y límite cumplido, al consultar con fecha de hoy (inyectar vía `guard.today` desfasado + mock de date **o** llamar `_rollover` cambiando `today` en el guard y usando `date.today()` — para no mockear, set `guard.today = date.today() - timedelta(days=1)` y `_seconds` alto, luego `add_seconds(0)` hoy ya resetea; **además** `is_over_limit` debe resetear si `date.today() != guard.today` sin add).
- [ ] Implementar `_rollover` usado por `add_seconds`, `is_over_limit`, `reset_today`.

```python
def _rollover(self) -> None:
    if date.today() != self.today:
        self.today = date.today()
        self._seconds = 0.0

def reset_today(self) -> None:
    self._rollover()
    self._seconds = 0.0
```

---

### Task 3: `RobotState` + API

**Files:**
- Modify: `ProyectoParaRasperrypiV5/api_server.py`

- [ ] Test en `test_sleep_state.py` o `test_api_power_sleep.py`: `RobotState()` default `sleep.phase()=="loading"` / no power; `to_dict()` keys; `update_config({"belly_wake_enabled": False})`.
- [ ] `RobotState` posee `sleep: SleepState`, `playtime_guard` ref opcional.
- [ ] `set_power(True)` → `request_wake("app")` + `note_parent_wake` + `playtime_guard.reset_today()` si existe.
- [ ] `set_power(False)` → `request_sleep("app")`.
- [ ] `to_dict`: `power_on=sleep.status_power_on()`, `models_ready`, `belly_wake_enabled`, `pending_wake`.
- [ ] Persist `belly_wake_enabled` en `parental_prefs.json`.
- [ ] Play/celebrate/story POST: si `not sleep.power_on` (despierto real), responder ok sin ejecutar.

`on_power_changed` se dispara con el **resultado real**: True solo si `phase()=="awake"` o se acaba de encolar (para ojos: si queued, seguir dormido; app.py usa `sleep.phase()`).

Callback: `on_power_changed(awake: bool)` donde awake es `phase()=="awake"`. Cola no cambia ojos a neutral. `on_wake_queued` opcional para reproducir clip: `on_not_ready_clip: Callable[[], None]`.

Más simple: `set_power` retorna `WakeResult` y el handler de API:

```python
result = robot_state.set_power(True)
if result == "queued" and robot_state.on_not_ready_clip:
    robot_state.on_not_ready_clip()
```

---

### Task 4: `SpeechWorker.play_canned_file` y `allow_when_asleep`

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py`
- Test: `test_sleep_state.py` (helpers puros) + test que `play_canned_file` retorna False si no existe el path (no requiere audio device).

```python
def play_canned_file(self, file_path: Path | str) -> bool:
    path = Path(file_path)
    if not path.exists():
        self._log(f"clip ausente: {path}")
        return False
    # reusar decode de play_audio_file SIN _is_playing_music ni notificación
    ...
    self._play_wav_via_output_stream(audio_array, sample_rate)
    return True

def speak(self, text: str, *, story: bool = False, allow_when_asleep: bool = False) -> None:
    if not allow_when_asleep:
        from api_server import robot_state as _rs
        sleep = getattr(_rs, "sleep", None)
        if sleep is not None and sleep.phase() != "awake":
            return
    ...
```

Evitar import circular: `SpeechWorker` recibe `power_gate: Callable[[], bool] | None = None` que retorna True si se puede hablar. App inyecta `lambda: robot_state.sleep.phase() == "awake"`. Preferible a importar api_server desde speak.

**Produces:** `speak(..., allow_when_asleep=False)`, `play_canned_file(path) -> bool`, opcional `set_power_gate(fn)`.

---

### Task 5: Gate de AudioWorker / CameraWorker / app.py / panza

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py`
- Modify: `ProyectoParaRasperrypiV5/app.py`

- [ ] Tras warmup LLM, `robot_state.sleep.mark_models_ready()`; si True, ojos neutral; si False, ojos dormido.
- [ ] Antes de `listen_until_cut`, si no awake: drenar `audio_queue` 0.2s y continue. No `_set_eyes("escuchando")` hasta awake.
- [ ] Camera loop: si no awake, `time.sleep(frame_interval)` y no inferir (modelos ya cargados).
- [ ] `_apply_power`: NO `stop_workers`. Solo ojos + `sleep` ya actualizado por API. Si awake, ojos neutral; si no, dormido.
- [ ] Default `_power_on = False` en EyeMode, Debug y Headless.
- [ ] API server se inicia **antes o junto** a workers; si hoy está después, mantener después está OK si el clip solo se necesita cuando alguien pide wake (workers speech ya existen). **Iniciar SpeechWorker antes de AudioWorker (ya es así).**
- [ ] `_on_belly`: `action = robot_state.sleep.on_belly()`; hug → `perform_hug_ask`; queue → `play_canned_file`; wake → ojos neutral; ignore → nop. Watcher se registra una vez al start workers (ya existe); no detenerlo al “apagar”.
- [ ] `_check_routines`: return si `sleep.phase() != "awake"`.
- [ ] `_on_celebrate` / play music-story: no-op si no awake (también en API).

Headless y Debug deben usar el mismo `_apply_power` de EyeMode (Headless ya lo alias). DebugApp `_on_power` hoy hace `stop_workers` — cambiarlo.

---

### Task 6: Voz (repregunta) y tope → sleep

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (turno, ~confirmación antes del canned farewell; playtime al final del turno)

Al inicio del procesamiento de un utterance, si `sleep.awaiting_sleep_confirm`:
- si `is_sleep_confirm_yes(text)`: speak goodnight `allow_when_asleep=True`, `request_sleep("child")`, ojos dormido, return.
- si no: `awaiting_sleep_confirm = False` y seguir el turno.

Después de game/yoga/story passthrough, si `is_sleep_request_text(sanitized_text)`:
- `awaiting_sleep_confirm = True`
- response = `SLEEP_CONFIRM_PHRASE`, skip LLM canned farewell.
- no apagar todavía.

Tras `playtime_guard.add_seconds`, si `is_over_limit()` y phase awake:
- speak `PLAYTIME_DECLINE_PHRASE` con `allow_when_asleep=True`
- `request_sleep("playtime")`
- ojos dormido

Tests de las funciones `is_sleep_*` ya en Task 1. Un test de fuente en workers opcional: que el archivo importe `is_sleep_request_text`.

---

### Task 7: Generar clip Edge TTS y assets

**Files:**
- Create: `ProyectoParaRasperrypiV5/scripts/generate_not_ready_clip.py`
- Create: `ProyectoParaRasperrypiV5/assets/todavia_no_estoy_listo.wav`

```powershell
python -m pip install edge-tts
python ProyectoParaRasperrypiV5/scripts/generate_not_ready_clip.py
```

El script: `edge_tts.Communicate(NOT_READY_TEXT, "es-AR-ElenaNeural")` → mp3 temp → decodificar con `av` o `soundfile` → escribir WAV PCM 16-bit mono/stereo 24000+. Si `av` no está, dejar mp3 y que `play_canned_file` use el decoder de música.

No commitear secretos. El WAV **sí** va al árbol (assets no está en gitignore).

---

### Task 8: Android chip + power status

**Files:**
- Modify: `ProyectoAndroid/app/src/main/res/layout/fragment_dashboard.xml`
- Modify: `ProyectoAndroid/app/src/main/res/values/strings.xml`
- Modify: `ProyectoAndroid/app/src/main/java/.../ui/dashboard/DashboardFragment.kt`
- Modify: `ProyectoAndroid/app/src/main/java/.../ui/dashboard/DashboardViewModel.kt`
- Modify: `ProyectoAndroid/app/src/main/java/.../network/RobotApiClient.kt`
- Modify: `ProyectoAndroid/app/src/main/java/.../network/RobotConnectionManager.kt`

Chip checkable debajo de `btn_power_toggle`:

```xml
<com.google.android.material.chip.Chip
    android:id="@+id/chip_belly_wake"
    android:layout_width="wrap_content"
    android:layout_height="wrap_content"
    android:layout_marginTop="8dp"
    android:checkable="true"
    android:checked="true"
    android:minHeight="48dp"
    android:text="@string/dashboard_belly_wake" />
```

`dashboard_belly_wake` = `Prender con el botón`.

`postConfigBellyWake(enabled: Boolean)` body `{"belly_wake_enabled": true}`.

Status: `optBoolean("power_on", false)` (default **false**, no true). Chip `optBoolean("belly_wake_enabled", true)`.

---

### Task 9: Subir a la Pi

Archivos Pi: `sleep_state.py`, `session_policy.py`, `api_server.py`, `app.py`, `workers.py`, `assets/todavia_no_estoy_listo.wav`, tests.

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put sleep_state.py session_policy.py api_server.py app.py workers.py test_sleep_state.py test_session_policy.py
```

WAV: `--put` desde `assets/` — el script pone en `PI_REMOTE_DIR`; crear `assets/` remoto si hace falta (el script de sftp debería crear dirs o subir con path `assets/todavia_no_estoy_listo.wav`).

No arrancar `app.py`.

---

## Spec coverage

| Spec | Task |
|---|---|
| Boot loading, modelos en RAM, API viva | 5 |
| Clip Edge + cola | 4, 5, 7 |
| Panza hug/wake/ignore + chip | 1, 5, 8 |
| App power + reset playtime | 2, 3 |
| Voz confirmación | 1, 6 |
| Tope → sleep + bloqueo panza | 1, 6 |
| Gate workers / rutinas / música | 5, 3 |
| Tests Windows | 1, 2 |
| Upload Pi | 9 |
