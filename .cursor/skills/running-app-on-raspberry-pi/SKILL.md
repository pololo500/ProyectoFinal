---
name: running-app-on-raspberry-pi
description: >-
  Run ProyectoParaRasperrypiV5 app.py on the Raspberry Pi over SSH and stream
  the live terminal log. Use when Teo asks to launch the peluche/app on the Pi,
  reproduce runtime errors from a terminal, watch AudioWorker/Whisper/TTS logs,
  or debug crashes without the Tk UI on Windows.
---

# Running app on Raspberry Pi

**Si hay que ver cómo corre en la Pi, ejecutalo vos por SSH. No le digas a Teo que abra una terminal.**

## Cuándo

- Reproducir errores de runtime (`Bus error`, `input overflow`, cámara/mic).
- Ver logs reales de `AudioWorker` / Whisper / Piper desde una terminal.
- Teo pide “corrélo en la Pi” o “mirá la salida”.

No arranques la app “por las dudas”; solo cuando haga falta diagnosticar o Teo lo pida.

## Cómo (cadena obligatoria)

1. Instalá `paramiko` si falta.
2. **Nunca** escribas `PI_SSH_PASS` en el repo ni en el skill.
3. En PowerShell (sin `&&`):

```powershell
$env:PI_SSH_PASS = '<clave, solo en esta sesión>'
python .cursor/skills/running-app-on-raspberry-pi/scripts/run_app_on_pi.py --seconds 45 --kill-existing
```

Si el skill está en `~/.cursor/skills/running-app-on-raspberry-pi/`, usá esa ruta.

4. Leé la salida streameada. El remoto corta con `timeout` al llegar a `--seconds`.
5. Para carga CPU/RAM en paralelo, usá la skill `measuring-pi-process-load`.

## Flags útiles

| Flag | Default | Uso |
|------|---------|-----|
| `--seconds` | `45` | Cuánto capturar antes de matar el proceso |
| `--kill-existing` | off | Mata `python … app.py` previos del usuario |
| `--entry` | `app.py` | Otro script en `PI_REMOTE_DIR` |
| `--extra-args` | vacío | Args extra al entry |

## Defaults (override por env)

| Env | Default |
|-----|---------|
| `PI_HOST` | `192.168.0.136` |
| `PI_USER` | `teo` |
| `PI_SSH_PASS` | obligatorio |
| `PI_REMOTE_DIR` | `/home/teo/Desktop/ProyectoFinal/ProyectoParaRasperrypiV5` |

Activa `venv` si existe. `DISPLAY=:0` por si Tk necesita el escritorio de la Pi.

## Prohibido

- Pedirle a Teo que corra `python app.py` a mano.
- Dejar la app corriendo horas sin `--seconds` / sin matarla.
- Meter la clave en git o en archivos del skill.
- `scp`/`ssh` interactivo (se cuelga pidiendo password).

## Notas

- Sin cámara o sin display, la UI Tk puede fallar o quedar rara; los logs de workers igual sirven.
- Si el log se inunda (ej. `input overflow`), acortá `--seconds` y cruzá con `measuring-pi-process-load`.
