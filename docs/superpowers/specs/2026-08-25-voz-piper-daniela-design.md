# Voz Piper más humana (Daniela AR) — diseño

Fecha: 2026-08-25  
Producto: peluche TEO (Raspberry Pi 5, 8 GB, CPU only)  
Estado: aprobado en conversación; pendiente de plan de implementación

## Problema

El TTS local suena robótico. El motor es Piper (correcto para la Pi), pero la voz activa es mexicana (`es_MX-claude-high`), `length_scale=1.25` estira la frase como lectura de máquina, y `Agents.md` todavía documenta `es_MX-ald-medium`. Si Piper no carga, el fallback es espeak-ng / SAPI, que sí suena a robot.

No hay margen de RAM/CPU para Kokoro, XTTS u otro motor: Whisper, spaCy y el LLM 1.8B ya corren juntos.

## Objetivo de esta iteración

Misma Piper, voz rioplatense y prosodia menos rígida, sin subir el presupuesto de recursos.

Criterio de éxito en la Pi: una frase tipo “¡Hola! Qué lindo que estés acá.” se oye con acento argentino, menos arrastre, sin cortes ni cambio de motor.

## Fuera de alcance

- Frases pregrabadas (opción B).
- Kokoro, XTTS, Bark u otro motor.
- Reescribir `intent_rules.json` ni el prompt del LLM.
- UI para elegir voz o velocidad.
- Nueva dependencia de resample (`soxr`, `scipy`).
- Borrar el ONNX viejo `es_MX-claude-high` del disco.
- Fallback intermedio a Claude si Daniela falla (sigue el fallback de plataforma).

## Arquitectura

El dueño del TTS sigue siendo `SpeechWorker` en `ProyectoParaRasperrypiV5/workers.py`.

```
texto → _strip_tts_markup → _prepare_tts_text → Piper (daniela-high) → sounddevice
                                              ↘ si Piper no está: SAPI / espeak-ng
```

No hay proceso nuevo, no hay cola extra, no hay cambio en `AudioWorker` ni en la app Android.

## Componentes

### 1. Modelo

| Campo | Valor |
|---|---|
| Nombre | `es_AR-daniela-high` |
| Archivos | `{nombre}.onnx` y `{nombre}.onnx.json` |
| Cache | `~/.edge_ai_models/piper/` |
| URL | `https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_AR/daniela/high/es_AR-daniela-high` + sufijo `.onnx` / `.onnx.json` |

`_ensure_piper_model()` deja de apuntar a `es_MX-claude-high`. Si Daniela ya está en cache, no se descarga de nuevo. Claude puede quedar en el mismo directorio sin usarse.

### 2. Síntesis

`SynthesisConfig` fijo (sin archivo de config):

| Parámetro | Valor | Notas |
|---|---|---|
| `length_scale` | `1.08` | Un poco pausada para nenes; no 1.25 |
| `noise_scale` | `0.667` | Default Piper, sin cambio |
| `noise_w_scale` | `0.90` | Un poco más de ritmo |

Si importar `piper.config.SynthesisConfig` falla, sintetizar sin kwargs (comportamiento actual).

### 3. Texto

Nuevo helper `_prepare_tts_text(text: str) -> str`, llamado después de `_strip_tts_markup` en `speak` / `speak_and_wait` (una sola vez, no de nuevo en `_speak_piper`).

Reglas:

1. Colapsar whitespace a un espacio.
2. Strip.
3. Si el texto no está vacío y el último carácter no es `.`, `!`, `?` ni `…`, agregar `.`.
4. No alterar el contenido de las frases.

`_strip_tts_markup` no cambia: saca `[…]` y `NOTIFY_PARENT`.

### 4. Docs

`ProyectoParaRasperrypiV5/Agents.md`: TTS = `piper-tts` con `es_AR-daniela-high` y los tres parámetros de la tabla. Quitar menciones a `es_MX-ald-medium`.

## Flujo de datos

Igual que hoy: `IntentDispatcher` / rutinas / cuentos / juegos encolan texto con `speak` o `speak_and_wait`. Solo cambia el modelo, los floats y el punto final opcional.

`CloudTTS` / gTTS no se modifica. El prepare de puntuación sí corre en modo nube porque vive en `speak` / `speak_and_wait` (camino común).

## Errores

- Descarga o `PiperVoice.load` falla: log `Error cargando modelo piper: …`, `_piper_voice = None`, fallback SAPI (Windows) o espeak-ng (Linux).
- `synthesize` no emite chunks: log `Piper no generó audio para el texto dado` y se pasa al siguiente ítem de la cola.
- Texto vacío tras strip/prepare: no encolar.

## Rollback

En `_ensure_piper_model` volver `es_MX-claude-high` y la URL `es/es_MX/claude/high/…`. En `SynthesisConfig` volver `length_scale=1.25`, `noise_w_scale=0.8`. El ONNX de Claude, si sigue en cache, no hace falta re-descargar.

## Pruebas

- Unit del nombre de modelo y de la URL (contiene `es_AR/daniela/high`).
- Unit de `SynthesisConfig`: `length_scale == 1.08`, `noise_scale == 0.667`, `noise_w_scale == 0.90`.
- Unit de `_prepare_tts_text`: `"hola"` → `"hola."`; `"¡Hola!"` no se modifica; espacios múltiples se colapsan; string vacío sigue vacío.
- `test_tts_playback.py` no cambia.
- Verificación en Pi (manual, no CI): reproducir “¡Hola! Qué lindo que estés acá.” Criterio: acento argentino, menos arrastre que Claude 1.25, sin cortes.

## Futuro (no esta iteración)

Opción B: WAV humanos para intenciones frecuentes, Piper para el resto.
