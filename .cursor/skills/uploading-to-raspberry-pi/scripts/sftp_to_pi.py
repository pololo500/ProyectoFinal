#!/usr/bin/env python3
"""SFTP files to the Raspberry Pi. Password only via PI_SSH_PASS (never commit it)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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


def connect() -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
    host = env("PI_HOST", "192.168.0.136")
    user = env("PI_USER", "teo")
    password = env("PI_SSH_PASS")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=15)
    return client, client.open_sftp()


def remote_path(remote_dir: str, local: Path) -> str:
    return f"{remote_dir.rstrip('/')}/{local.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Subir o borrar archivos en la Raspberry Pi")
    parser.add_argument("--put", nargs="*", default=[], help="Archivos locales a subir (basename en la Pi)")
    parser.add_argument("--delete", nargs="*", default=[], help="Nombres a borrar en PI_REMOTE_DIR")
    args = parser.parse_args()
    if not args.put and not args.delete:
        parser.error("pasá --put y/o --delete")

    remote_dir = env(
        "PI_REMOTE_DIR",
        "/home/teo/Desktop/ProyectoFinal/ProyectoParaRasperrypiV5",
    )
    client, sftp = connect()
    try:
        for raw in args.put:
            local = Path(raw).resolve()
            if not local.is_file():
                sys.stderr.write(f"no existe: {local}\n")
                return 1
            dest = remote_path(remote_dir, local)
            sftp.put(str(local), dest)
            print("ok", local.name, local.stat().st_size)
        for name in args.delete:
            dest = f"{remote_dir.rstrip('/')}/{Path(name).name}"
            try:
                sftp.remove(dest)
                print("rm", Path(name).name)
            except FileNotFoundError:
                print("missing", Path(name).name)
    finally:
        sftp.close()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
