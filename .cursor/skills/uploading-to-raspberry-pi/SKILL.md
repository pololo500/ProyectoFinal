---
name: uploading-to-raspberry-pi
description: >-
  Use when local files that should run on the Raspberry Pi were created, edited,
  or deleted; when deploying to the peluche, edge device, teo@192.168.0.136,
  ProyectoParaRasperrypiV5; or when tempted to tell the user to scp/sftp instead
  of uploading. Use after any code change meant to run on the Pi.
---

# Uploading to Raspberry Pi

**Si el archivo tiene que ejecutarse en la Pi, subilo vos. No dejes el cambio solo en Windows.**

Violar la letra es violar el espíritu. Decirle a Teo que copie con `scp` no cuenta como subir.

## Cuándo

Después de crear, editar o borrar archivos que la Pi usa (`*.py`, tests, JSON, modelos de config, `requirements.txt`). Antes de decir "copiá esto" o "reiniciá app.py".

No aplica a README/docs que no corren en el dispositivo, ni a secretos (`.env`, claves).

## Cómo (cadena obligatoria)

1. Instalá `paramiko` si falta (`python -m pip install paramiko` o `uv pip install paramiko`).
2. **Nunca** pongas la contraseña en un archivo del repo, del skill, ni en `/tmp` versionable.
3. En PowerShell, pasá la clave solo por env de esa invocación y ejecutá el script de **esta** skill:

```powershell
$env:PI_SSH_PASS = '<clave de teo, solo en memoria de la sesión>'
python .cursor/skills/uploading-to-raspberry-pi/scripts/sftp_to_pi.py --put workers.py app.py
```

Si el skill está en `~/.cursor/skills/uploading-to-raspberry-pi/`, usá esa ruta al `.py`.

Borrar en la Pi:

```powershell
python .cursor/skills/uploading-to-raspberry-pi/scripts/sftp_to_pi.py --delete mic_tcp.py
```

4. Comprobá la salida: cada `--put` imprime `ok <nombre> <bytes>`. Si falla SSH, reintentá; no caigas a "copialo vos".
5. No arranques `app.py` en la Pi salvo que Teo lo pida. Avisá que hay que reiniciar el proceso que ya corre.

## Defaults (override por env)

| Env | Default |
|-----|---------|
| `PI_HOST` | `192.168.0.136` |
| `PI_USER` | `teo` |
| `PI_SSH_PASS` | obligatorio; no hay default en el skill |
| `PI_REMOTE_DIR` | `/home/teo/Desktop/ProyectoFinal/ProyectoParaRasperrypiV5` |

PowerShell: no uses `&&`. No metas Python con `python -c` y comillas anidadas: usá el script.

## Prohibido

- `scp` interactivo (pide clave y se cuelga).
- Dejar el upload "para que Teo lo haga".
- Escribir `PI_SSH_PASS` o `12345` en git, SKILL.md, o scripts commiteados.
- Asumir que hay clave SSH configurada (en esta Pi suele no haberla).

## Exportar a otro repo o branch

Copiá **toda** la carpeta:

```
uploading-to-raspberry-pi/
  SKILL.md
  scripts/sftp_to_pi.py
```

- Otro branch/repo: `.cursor/skills/uploading-to-raspberry-pi/`
- Todos los proyectos de Cursor: `~/.cursor/skills/uploading-to-raspberry-pi/`

Ajustá `PI_REMOTE_DIR` / `PI_HOST` si el otro repo no vive en ese path.

## Excusas

| Excusa | Realidad |
|--------|----------|
| "Le digo que haga scp" | El agente sube. scp se traba pidiendo clave. |
| "No hay clave SSH" | Por eso paramiko + `PI_SSH_PASS`. |
| "El cambio es chico" | La Pi no ve el archivo hasta el SFTP. |
| "Windows no puede" | El script corre en Windows. |
| "Lo dejo para el final" | Subí en el mismo turno en que editaste. |
