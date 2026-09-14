# Piso de volumen para endpointing del micrófono — diseño

Fecha: 2026-09-13  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

En la Pi el VAD de captura es por energía (`energy-vad`). El medidor de la UI es `volumen % = min(100, int(RMS × 300))`. El umbral de arranque del adaptador es RMS `0.012` (~4 % en ese medidor). Ruido ambiental al ~5 % arranca “escuchando…” y corre el tope de captura (`MAX_LISTEN_SECONDS = 8`).

Ese recorte no distingue ruido de voz. El audio que se manda al servidor Windows debe seguir siendo el clip crudo.

## Objetivo

1. Todo bloque con volumen de UI **&lt; 30 %** cuenta como silencio **solo** para decidir si arranca o se corta la escucha.
2. El WAV / array que viaja a STT local o `ServidorDePC` no se gatea, no se silencia y no se recorta por este piso.
3. Subir el tope duro de captura de **8 s a 12 s**.

## Fuera de alcance (v1)

- Cambiar `SileroVadAdapter.ENERGY_START` / `ENERGY_CONTINUE`.
- Histéresis (un umbral de arranque y otro de continuación por debajo de 30).
- Gate, normalización o filtro sobre el audio enviado.
- Cambiar el medidor de la UI (sigue mostrando el % real, aunque sea 5).
- Cambiar umbrales de silencio temporal (`NORMAL_SILENCE` 1.2 s / `EXTENDED_SILENCE` 3.0 s).
- Preproceso STT, `pc_server_client`, cloud, TTS, cámara.

## Decisiones

- **Escala:** el 30 % es el mismo número que “Volumen micrófono” en la UI (`RMS × 300`, tope 100). Equivale a RMS `0.10`. No es 30 % de escala absoluta del sample.
- **Un solo piso:** `LISTEN_VOLUME_FLOOR_PCT = 30`. `volume_pct >= 30` puede contar como voz; `volume_pct < 30` es silencio de endpointing. Sin histéresis.
- **Conjunción:** hay voz para el corte solo si el piso se cumple **y** `vad.has_speech(audio_block)`. Si el piso falla, no hace falta que el VAD diga voz (short-circuit válido).
- **Audio crudo:** con `speech_active`, los bloques bajo el piso se siguen appendeando a `current_segment`. El pre-roll del circular buffer no se limpia por volumen. El array concatenado es el que se transcribe / POST al PC.
- **Tope:** `AudioWorker.MAX_LISTEN_SECONDS = 12.0`. Sigue ganando el primero entre silencio VAD (1.2 / 3.0 s) y este máximo.
- **Errores de RMS:** NaN, inf o excepción al calcular volumen → `volume_pct = 0` → silencio de endpointing (igual que hoy para el medidor).

## Arquitectura

El piso vive en el loop `listen_until_cut` de `AudioWorker`. No entra en el adaptador VAD ni en el cliente HTTP.

```
bloque mic (crudo)
    → medidor UI (RMS × 300)          # status; no decide el WAV
    → volume_counts_as_speech(pct)    # solo endpointing
          ├─ False → silencio (no arranca; si ya escuchaba, suma hangover)
          └─ True  → vad.has_speech → arranca / sigue voz
    → current_segment += bloque crudo  # si speech_active
    → corte: 1.2/3.0 s silencio o 12 s tope
    → STT Pi o POST WAV al servidor PC (sin gate)
```

## Unidades

### `volume_counts_as_speech` (`workers.py`)

| | |
|---|---|
| Hace | `True` si el % del medidor es voz para cortar/arrancar |
| Uso | `volume_counts_as_speech(volume_pct, floor_pct=LISTEN_VOLUME_FLOOR_PCT)` |
| Depende | nada (enteros) |

```python
LISTEN_VOLUME_FLOOR_PCT = 30

def volume_counts_as_speech(
    volume_pct: int,
    floor_pct: int = LISTEN_VOLUME_FLOOR_PCT,
) -> bool:
    return int(volume_pct) >= int(floor_pct)
```

### `AudioWorker.listen_until_cut` (`workers.py`)

Tras calcular `volume_pct` (igual que hoy) y publicar el status:

```python
speech_detected = volume_counts_as_speech(volume_pct) and vad.has_speech(audio_block)
```

El resto del hangover, pre-roll, drops y concatenación no cambia.

### `AudioWorker.MAX_LISTEN_SECONDS`

De `8.0` a `12.0`. Comentario y `docs/LATENCIA_AUDIO_CAMARA.md` punto 10 alineados.

## Comportamiento esperado

| Medidor | Estado previo | Efecto |
|---|---|---|
| 5 % o 29 % | idle | no arranca “escuchando…” |
| 30 % o 50 % | idle | si el VAD también dice voz, arranca |
| &lt; 30 % | escuchando | el bloque entra crudo al segmento; suma silencio; corta a 1.2 s (o 3.0 si triste/enojado) |
| ≥ 30 % | escuchando | silencio se resetea si el VAD dice voz |
| cualquier % | escuchando 12 s | corte por tiempo máximo, audio crudo |

Voz real por debajo de 30 % en el medidor **no** dispara escucha. Es el costo aceptado del piso.

## Tests

En `ProyectoParaRasperrypiV5/test_mic_input.py`:

- `volume_counts_as_speech(5)` y `(29)` → `False`; `(30)` y `(50)` → `True`.
- `AudioWorker.MAX_LISTEN_SECONDS == 12.0` (reemplaza `test_max_listen_es_8`).
- El loop usa `volume_counts_as_speech` **antes** de tratar el bloque como voz (assert de fuente, mismo estilo que otros tests de `workers.py`).
- El loop **no** pone a cero ni atenúa `audio_block` / `current_segment` por el piso.

## Rollback

| Palanca | Nuevo | Anterior | Cómo volver |
|---|---|---|---|
| Piso UI | 30 % | ~4 % (`ENERGY_START` 0.012) | `LISTEN_VOLUME_FLOOR_PCT = 0` o quitar el `and` |
| Tope captura | 12.0 s | 8.0 s | `MAX_LISTEN_SECONDS = 8.0` |
