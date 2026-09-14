# Piso de volumen para endpointing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD. Sin `git commit` salvo pedido de Teo.

**Goal:** En la Pi, el medidor de micrófono por debajo de 30 % cuenta como silencio para arrancar o cortar la escucha; el audio que se manda al servidor Windows sigue crudo; el tope duro de captura pasa de 8 s a 12 s.

**Architecture:** Helper puro `volume_counts_as_speech(volume_pct)` con piso `LISTEN_VOLUME_FLOOR_PCT = 30` (misma escala que la UI: `min(100, int(RMS × 300))`). En `listen_until_cut`, `speech_detected` es el AND de ese helper y `vad.has_speech`. No se toca `SileroVadAdapter`, ni el WAV, ni `pc_server_client`.

**Tech Stack:** Python 3.11, `unittest` (`python -m unittest …` desde `ProyectoParaRasperrypiV5`), numpy ya en el proyecto.

**Spec:** `docs/superpowers/specs/2026-09-13-listen-volume-floor-design.md`

## Global Constraints

- El 30 % es el medidor UI (`RMS × 300`), no 30 % de escala absoluta del sample (eso sería RMS 0.30).
- Un solo piso: `LISTEN_VOLUME_FLOOR_PCT = 30`. Sin histéresis.
- Conjunción exacta: `speech_detected = volume_counts_as_speech(volume_pct) and vad.has_speech(audio_block)`.
- El array concatenado / WAV al STT local o `ServidorDePC` no se gatea, no se silencia y no se recorta por este piso.
- No cambiar `SileroVadAdapter.ENERGY_START = 0.012` ni `ENERGY_CONTINUE = 0.006`.
- No cambiar `EmotionReactor.NORMAL_SILENCE` (1.2) ni `EXTENDED_SILENCE` (3.0).
- El medidor UI sigue publicando el % real (`{"mic": mic_label, "volume": volume_pct}`), aunque sea 5.
- `AudioWorker.MAX_LISTEN_SECONDS = 12.0` (antes 8.0). Gana el primero entre silencio VAD y este máximo.
- TDD: test rojo **antes** de producción. unittest, **no pytest**.
- Sin commit salvo pedido de Teo (omitir todos los `git commit`).
- Tras cada cambio de producción en `workers.py`: subir con el skill `uploading-to-raspberry-pi`. `PI_REMOTE_DIR=/home/teo/Desktop/ProyectoParaRasperrypiV5`. **NUNCA** arrancar `app.py` salvo que Teo lo pida.
- Upload (PowerShell, cwd del archivo local; **no** `&&`; clave solo en env de la invocación):

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put workers.py
```

Esperado: `ok workers.py <bytes>`.

---

## File structure

- Modify: `ProyectoParaRasperrypiV5/workers.py` — constante `LISTEN_VOLUME_FLOOR_PCT`, helper `volume_counts_as_speech`, conjunción en `listen_until_cut`, `MAX_LISTEN_SECONDS = 12.0`.
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py` — tests del helper, del AND en fuente, del tope 12, guardia de audio crudo.
- Modify: `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md` — punto 10: tope 12.0, rollback 8.0.

No crear archivos nuevos. No tocar `pc_server_client.py`, `cloud_services.py`, `SileroVadAdapter`, ni el cálculo `rms * 300`.

---

### Task 1: Helper `volume_counts_as_speech`

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py` (después de `AUDIO_QUEUE_MAXSIZE = 128`, ~línea 979; función junto a `vad_log_label`, ~línea 982)
- Test: `ProyectoParaRasperrypiV5/test_mic_input.py`

**Interfaces:**
- Consumes: nada
- Produces: `LISTEN_VOLUME_FLOOR_PCT: int = 30`; `volume_counts_as_speech(volume_pct: int, floor_pct: int = LISTEN_VOLUME_FLOOR_PCT) -> bool`

- [ ] **Step 1: Write the failing tests**

En `ProyectoParaRasperrypiV5/test_mic_input.py`, agregar `LISTEN_VOLUME_FLOOR_PCT` y `volume_counts_as_speech` al import de `workers` (líneas 10–26):

```python
from workers import (
    AUDIO_QUEUE_MAXSIZE,
    LISTEN_VOLUME_FLOOR_PCT,
    AudioWorker,
    EmotionReactor,
    apply_capture_drops,
    capture_hop_seconds,
    downsample_capture_to_stt,
    enqueue_mic_block,
    find_supported_input_config,
    mic_block_to_stt,
    pcm_s16le_to_float32,
    pi_mic_capture_rate,
    stt_block_duration_seconds,
    vad_circular_maxlen,
    vad_log_label,
    vad_pre_roll_blocks,
    volume_counts_as_speech,
)
```

Agregar esta clase **antes** de `class TestDocsArecord` (antes de la ~línea 319):

```python
class TestListenVolumeFloor(unittest.TestCase):
    def test_piso_es_30(self) -> None:
        self.assertEqual(LISTEN_VOLUME_FLOOR_PCT, 30)

    def test_ruido_bajo_no_cuenta_como_voz(self) -> None:
        self.assertFalse(volume_counts_as_speech(5))
        self.assertFalse(volume_counts_as_speech(29))

    def test_treinta_o_mas_cuenta_como_voz(self) -> None:
        self.assertTrue(volume_counts_as_speech(30))
        self.assertTrue(volume_counts_as_speech(50))
```

- [ ] **Step 2: Run tests to verify they fail**

Working directory: `ProyectoParaRasperrypiV5`

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestListenVolumeFloor -v
```

Expected: FAIL/ERROR at import: `cannot import name 'LISTEN_VOLUME_FLOOR_PCT'` y/o `cannot import name 'volume_counts_as_speech'` from `workers`. Si el import se mueve dentro de los métodos y las constantes no existen, `AttributeError`. No debe ser PASS.

- [ ] **Step 3: Write minimal implementation**

En `ProyectoParaRasperrypiV5/workers.py`, inmediatamente después de `AUDIO_QUEUE_MAXSIZE = 128`:

```python
AUDIO_QUEUE_MAXSIZE = 128
LISTEN_VOLUME_FLOOR_PCT = 30
```

Inmediatamente después de `vad_log_label`:

```python
def vad_log_label(mode: str) -> str:
    """Prefijo de log: en aarch64 el VAD real es energía, no Silero."""
    return "silero-vad" if mode == "silero" else "energy-vad"


def volume_counts_as_speech(
    volume_pct: int,
    floor_pct: int = LISTEN_VOLUME_FLOOR_PCT,
) -> bool:
    """True si el % del medidor UI cuenta como voz para arrancar/cortar."""
    return int(volume_pct) >= int(floor_pct)
```

No cambiar `listen_until_cut` en esta tarea.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestListenVolumeFloor -v
```

Expected: 3 tests OK.

- [ ] **Step 5: Commit**

Omitir salvo que Teo lo pida.

---

### Task 2: Conjunción en `listen_until_cut` (piso AND VAD)

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py:1642`
- Test: `ProyectoParaRasperrypiV5/test_mic_input.py` (clase `TestListenVolumeFloor` de la Task 1)

**Interfaces:**
- Consumes: `volume_counts_as_speech(volume_pct: int, floor_pct: int = LISTEN_VOLUME_FLOOR_PCT) -> bool` (Task 1)
- Produces: en `listen_until_cut`, voz para endpointing solo si el medidor ≥ 30 **y** `vad.has_speech`; `current_segment` sigue appendeando `audio_block` crudo

- [ ] **Step 1: Write the failing tests**

Agregar estos métodos a `TestListenVolumeFloor` en `ProyectoParaRasperrypiV5/test_mic_input.py`:

```python
    def test_corte_exige_piso_y_vad(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn(
            "speech_detected = volume_counts_as_speech(volume_pct) and vad.has_speech(audio_block)",
            src,
        )
        self.assertNotIn(
            "speech_detected = vad.has_speech(audio_block)",
            src,
        )

    def test_piso_no_mutea_el_bloque_crudo(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        start = src.find("def listen_until_cut")
        end = src.find("return None", start)
        body = src[start:end]
        self.assertGreater(start, 0)
        self.assertIn("current_segment.append(audio_block)", body)
        self.assertNotIn("audio_block = np.zeros", body)
        self.assertNotIn("audio_block *= 0", body)
        self.assertNotIn("_noise_gate(", body)

    def test_medidor_ui_sigue_rms_por_300(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn("volume_pct = min(100, int(rms * 300))", src)
        self.assertIn('{"mic": mic_label, "volume": volume_pct}', src)

    def test_energy_vad_umbrales_no_cambian(self) -> None:
        src = _WORKERS.read_text(encoding="utf-8")
        self.assertIn("ENERGY_START = 0.012", src)
        self.assertIn("ENERGY_CONTINUE = 0.006", src)
```

- [ ] **Step 2: Run tests to verify the new one fails for the right reason**

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestListenVolumeFloor -v
```

Expected:
- `test_corte_exige_piso_y_vad` FAIL: `speech_detected = volume_counts_as_speech(...)` not found (hoy la línea es `speech_detected = vad.has_speech(audio_block)`).
- `test_piso_no_mutea_el_bloque_crudo` PASS (ya no mutea).
- `test_medidor_ui_sigue_rms_por_300` PASS.
- `test_energy_vad_umbrales_no_cambian` PASS.
- Los 3 tests de la Task 1 PASS.

Si `test_corte_exige_piso_y_vad` PASS sin haber tocado `listen_until_cut`, el assert está mal: parar.

- [ ] **Step 3: Write minimal implementation**

En `ProyectoParaRasperrypiV5/workers.py`, reemplazar **solo** esta línea (hoy ~1642, dentro de `listen_until_cut`, después del `continue` del mute de eco):

```python
                    speech_detected = vad.has_speech(audio_block)
```

por:

```python
                    speech_detected = volume_counts_as_speech(volume_pct) and vad.has_speech(audio_block)
```

No alterar el cálculo de `volume_pct`, el `status` del medidor, `current_segment.append(audio_block)`, ni `SileroVadAdapter`.

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestListenVolumeFloor -v
```

Expected: todos OK (7 tests).

- [ ] **Step 5: Upload `workers.py` to the Pi**

Leer y seguir `C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\SKILL.md`. Desde `ProyectoParaRasperrypiV5`:

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put workers.py
```

Expected: `ok workers.py <bytes>`. No arrancar `app.py`.

- [ ] **Step 6: Commit**

Omitir salvo que Teo lo pida.

---

### Task 3: Tope de captura 12 s y doc de latencia

**Files:**
- Modify: `ProyectoParaRasperrypiV5/workers.py:1123-1125`
- Modify: `ProyectoParaRasperrypiV5/test_mic_input.py:274-275`
- Modify: `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md:36-39`

**Interfaces:**
- Consumes: nada nuevo
- Produces: `AudioWorker.MAX_LISTEN_SECONDS: float = 12.0`

- [ ] **Step 1: Write the failing tests**

En `ProyectoParaRasperrypiV5/test_mic_input.py`, reemplazar `test_max_listen_es_8` (clase `TestEndpointingYCola`) por:

```python
    def test_max_listen_es_12(self) -> None:
        self.assertAlmostEqual(AudioWorker.MAX_LISTEN_SECONDS, 12.0)
```

Borrar por completo `test_max_listen_es_8`. No dejar los dos.

En `TestDocsArecord.test_latencia_documenta_pipewire_y_no_sudo` **no** mezclar este assert. Agregar método nuevo en `TestDocsArecord`:

```python
    def test_latencia_documenta_tope_12(self) -> None:
        text = Path(__file__).resolve().parent.joinpath(
            "docs", "LATENCIA_AUDIO_CAMARA.md"
        ).read_text(encoding="utf-8")
        self.assertIn("MAX_LISTEN_SECONDS`: **12.0**", text)
        self.assertNotIn("MAX_LISTEN_SECONDS`: **8.0**", text)
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestEndpointingYCola.test_max_listen_es_12 test_mic_input.TestDocsArecord.test_latencia_documenta_tope_12 -v
```

Expected:
- `test_max_listen_es_12` FAIL: `8.0 != 12.0` (o `8.0 != 12` en el almostEqual).
- `test_latencia_documenta_tope_12` FAIL: `MAX_LISTEN_SECONDS`: **12.0** not found.

No debe ser PASS.

- [ ] **Step 3: Write minimal implementation**

En `ProyectoParaRasperrypiV5/workers.py`, reemplazar el bloque de clase `AudioWorker`:

```python
    # Tope duro de captura: silencio (VAD) o este máximo, lo que ocurra primero.
    # LATENCIA punto 10: 8.0. Rollback (cuentos largos): 15.0.
    MAX_LISTEN_SECONDS: float = 8.0
```

por:

```python
    # Tope duro de captura: silencio (VAD) o este máximo, lo que ocurra primero.
    # LATENCIA punto 10: 12.0. Rollback: 8.0.
    MAX_LISTEN_SECONDS: float = 12.0
```

En `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md`, reemplazar el punto 10 entero:

```markdown
### 10. Tope de escucha
- `AudioWorker.MAX_LISTEN_SECONDS`: **12.0** (el **8.0** cortaba si el ruido arrancaba el turno; 15.0 dejaba turnos largos)
- **Síntoma si 12 está mal:** corta cuentos o frases largas a los 12 s, o el turno se alarga con voz real.
- **Revertir:** 8.0.
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.TestEndpointingYCola.test_max_listen_es_12 test_mic_input.TestDocsArecord.test_latencia_documenta_tope_12 test_mic_input.TestListenVolumeFloor -v
```

Expected: todos OK. `test_max_listen_es_8` ya no existe (si unittest lo lista, el rename falló).

- [ ] **Step 5: Upload `workers.py` to the Pi**

```powershell
$env:PI_REMOTE_DIR = '/home/teo/Desktop/ProyectoParaRasperrypiV5'
python C:\Users\polol\.cursor\skills\uploading-to-raspberry-pi\scripts\sftp_to_pi.py --put workers.py
```

Expected: `ok workers.py <bytes>`. No arrancar `app.py`.

- [ ] **Step 6: Commit**

Omitir salvo que Teo lo pida.

---

### Task 4: Verificar suite de micrófono

**Files:**
- Test only: `ProyectoParaRasperrypiV5/test_mic_input.py`
- No production edits.

**Interfaces:**
- Consumes: Tasks 1–3
- Produces: suite verde

- [ ] **Step 1: Run the full mic test file**

Working directory: `ProyectoParaRasperrypiV5`

```powershell
.\venv\Scripts\python.exe -m unittest test_mic_input.py -v
```

Expected: Ran N tests (N ≥ los que ya había + 7 de floor + 1 de tope 12 + 1 de doc; −1 del tope 8), OK, sin ERROR ni FAIL. `test_silencio_normal_es_1_2` sigue PASS (1.2 / 3.0).

Si algo falla, arreglar en el archivo de esa tarea; no “seguir de largo”.

- [ ] **Step 2: Commit**

Omitir salvo que Teo lo pida.

---

## Self-review (spec coverage)

| Spec | Task |
|---|---|
| Piso 30 % del medidor UI para endpointing | Task 1 + 2 |
| Audio crudo al PC / STT | Task 2 `test_piso_no_mutea_el_bloque_crudo` |
| Medidor UI sin cambiar | Task 2 `test_medidor_ui_sigue_rms_por_300` |
| No tocar ENERGY_START/CONTINUE | Task 2 `test_energy_vad_umbrales_no_cambian` |
| Sin histéresis | Task 1 (un `>=` contra 30) |
| MAX_LISTEN 12 s + rollback 8 s en LATENCIA | Task 3 |
| NORMAL_SILENCE 1.2 intacto | Task 4 (`test_silencio_normal_es_1_2`) |
| Tests 5/29 False, 30/50 True | Task 1 |
| AND en fuente de `listen_until_cut` | Task 2 |
