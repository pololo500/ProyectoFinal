#!/usr/bin/env python3
"""Run app.py on the Raspberry Pi over SSH and stream stdout/stderr.

Password only via PI_SSH_PASS (never commit it).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

try:
    import paramiko
except ImportError:
    sys.stderr.write("paramiko no está instalado. Corré: python -m pip install paramiko\n")
    sys.exit(1)


def env(name: str, default: str | None = None) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    if default is not None:
        return default
    sys.stderr.write(f"Falta {name}. Definila en el entorno; no la escribas en el repo.\n")
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ejecutar app.py en la Pi por SSH y ver la salida")
    parser.add_argument(
        "--entry",
        default="app.py",
        help="Script a ejecutar (default: app.py)",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=45,
        help="Segundos máximos de captura antes de matar el proceso (default: 45)",
    )
    parser.add_argument(
        "--kill-existing",
        action="store_true",
        help="Matar procesos python app.py previos del usuario antes de arrancar",
    )
    parser.add_argument(
        "--extra-args",
        default="",
        help="Argumentos extra para el entry (una sola string)",
    )
    args = parser.parse_args()

    host = env("PI_HOST", "192.168.0.136")
    user = env("PI_USER", "teo")
    password = env("PI_SSH_PASS")
    remote_dir = env(
        "PI_REMOTE_DIR",
        "/home/teo/Desktop/ProyectoFinal/ProyectoParaRasperrypiV5",
    )

    kill_prefix = ""
    if args.kill_existing:
        # No usar pkill -f: el cmdline del wrapper SSH contiene "app.py" y se suicida.
        kill_prefix = (
            'self=$$; '
            'ps -u "$USER" -o pid=,comm=,args= | while read -r pid comm args; do '
            '  case "$comm" in python|python3|python3.*) ;; *) continue ;; esac; '
            '  case "$args" in *app.py*) ;; *) continue ;; esac; '
            '  if [ "$pid" != "$self" ]; then kill "$pid" 2>/dev/null || true; fi; '
            'done; sleep 1; '
        )

    extra = (args.extra_args or "").strip()
    entry = args.entry.strip() or "app.py"
    # Unbuffered so logs stream; DISPLAY may be needed for Tk on the Pi desktop.
    remote_cmd = (
        f"export PATH=\"$HOME/.local/bin:$PATH\"; "
        f"cd {remote_dir!s} && "
        f"{kill_prefix}"
        f"if [ -f venv/bin/activate ]; then . venv/bin/activate; fi; "
        f"export DISPLAY=\"${{DISPLAY:-:0}}\"; "
        f"export PYTHONUNBUFFERED=1; "
        f"timeout {int(args.seconds)}s python -u {entry} {extra} 2>&1; "
        f"echo \"__PI_APP_EXIT__ $?\" "
    )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            username=user,
            password=password,
            timeout=20,
            banner_timeout=60,
            auth_timeout=30,
        )
    except Exception as exc:
        sys.stderr.write(
            f"SSH falló ({host}): {exc}\n"
            "Si la Pi está saturada, cerrá la app en el escritorio o reiniciá y reintentá.\n"
        )
        return 1
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)

    print(f"# ssh {user}@{host}  dir={remote_dir}  entry={entry}  seconds={args.seconds}")
    try:
        _stdin, stdout, _stderr = client.exec_command(remote_cmd, get_pty=True)
        chan = stdout.channel
        chan.settimeout(1.0)
        deadline = time.monotonic() + float(args.seconds) + 30.0
        while True:
            drained = False
            if chan.recv_ready():
                chunk = chan.recv(8192)
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
                drained = True
            if chan.recv_stderr_ready():
                chunk = chan.recv_stderr(8192)
                sys.stderr.buffer.write(chunk)
                sys.stderr.flush()
                drained = True
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if time.monotonic() > deadline:
                sys.stderr.write("\n# timeout local: cerrando canal\n")
                chan.close()
                break
            if not drained:
                time.sleep(0.12)
        code = chan.recv_exit_status() if chan.exit_status_ready() else 124
        return int(code)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
