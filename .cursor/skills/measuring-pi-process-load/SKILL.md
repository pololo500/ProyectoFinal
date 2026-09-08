---
name: measuring-pi-process-load
description: >-
  SSH into the Raspberry Pi and sample CPU, RAM, thermal, and top processes
  (python/app.py/whisper/piper). Use when the peluche feels slow, the console
  floods with Audio callback / input overflow, diagnosing Pi overload, or Teo
  asks what is consuming resources on the edge device.
---

# Measuring Pi process load

**Si la Pi está lenta o el log se llena, medí vos la carga por SSH. No le pidas a Teo que corra `top`.**

## Cuándo

- Consola inundada (`input overflow`, callbacks de mic).
- La Pi se pone lenta / térmica / swap.
- Cruzar con `running-app-on-raspberry-pi` mientras `app.py` corre.
- Teo pregunta “qué está comiendo CPU/RAM”.

## Cómo (cadena obligatoria)

1. Instalá `paramiko` si falta.
2. **Nunca** escribas `PI_SSH_PASS` en el repo ni en el skill.
3. En PowerShell (sin `&&`):

```powershell
$env:PI_SSH_PASS = '<clave, solo en esta sesión>'
python .cursor/skills/measuring-pi-process-load/scripts/measure_pi_load.py --samples 6 --interval 2
```

Si el skill está en `~/.cursor/skills/measuring-pi-process-load/`, usá esa ruta.

4. Interpretá: loadavg, %CPU estimado, MemAvailable, top por **proceso**, top por **hilo** (`ps -eL` acumulado y delta de `/proc/PID/task` en los PIDs que matchean).
5. Si necesitás logs de la app al mismo tiempo, usá `running-app-on-raspberry-pi` en otra invocación.

## Flags útiles

| Flag | Default | Uso |
|------|---------|-----|
| `--samples` | `6` | Cantidad de muestras |
| `--interval` | `2` | Segundos entre muestras |
| `--match` | `python\|app\.py\|whisper\|piper` | Regex de procesos a destacar |
| `--top` | `12` | Filas del ranking por CPU |

## Defaults (override por env)

| Env | Default |
|-----|---------|
| `PI_HOST` | `192.168.0.136` |
| `PI_USER` | `teo` |
| `PI_SSH_PASS` | obligatorio |

No requiere `PI_REMOTE_DIR` (mide el sistema completo).

## Cómo leer el output

- **loadavg** alto sostenido (> núcleos) → contención de CPU.
- **MemAvailable** bajo / used alto → riesgo de thrashing; Whisper `medium` come mucho.
- Procesos `python`/`app.py` con %CPU alto + spam de `input overflow` → el callback del mic no vacía a tiempo (CPU ocupada o cola bloqueada).
- Un proceso `python` al 50% puede ser un hilo (AudioWorker, Whisper, llama.cpp) o muchos sumados: mirá `COMM`/`TID` del bloque de hilos, no solo el PID.
- Temperatura > ~80 C → thermal throttling.

## Prohibido

- Pedirle a Teo que abra `htop` / `top`.
- Escribir la clave en git o en el skill.
- `ssh` interactivo.
- Inventar números: solo lo que imprime el script.

## Exportar

Copiá toda la carpeta:

```
measuring-pi-process-load/
  SKILL.md
  scripts/measure_pi_load.py
```
