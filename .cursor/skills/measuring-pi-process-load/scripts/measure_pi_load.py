#!/usr/bin/env python3
"""Sample CPU/RAM and top processes on the Raspberry Pi over SSH.

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


def build_remote_script(
    samples: int,
    interval: float,
    match: str,
    top_n: int,
) -> str:
    # Runs entirely on the Pi with /bin/sh-compatible python3.
    return f"""
export PATH="$HOME/.local/bin:$PATH"
python3 - <<'PY'
import os, time, subprocess, re

SAMPLES = {int(samples)}
INTERVAL = {float(interval)}
MATCH = {match!r}
TOP_N = {int(top_n)}

def sh(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
    except Exception as exc:
        return f"ERR: {{exc}}"

def meminfo():
    total = avail = None
    for line in open("/proc/meminfo"):
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
    used = (total - avail) if total and avail is not None else None
    return total, avail, used

def loadavg():
    return open("/proc/loadavg").read().strip()

def cpu_stat():
    # idle + total jiffies
    with open("/proc/stat") as f:
        parts = f.readline().split()
    nums = list(map(int, parts[1:]))
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    total = sum(nums)
    return idle, total

def top_ps(n: int):
    # pid, %cpu, %mem, rss_kb, cmd
    out = sh("ps -eo pid,pcpu,pmem,rss,comm,args --sort=-pcpu")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return []
    header, rows = lines[0], lines[1:]
    return [header] + rows[:n]

def match_ps(pat: str):
    out = sh("ps -eo pid,pcpu,pmem,rss,etime,comm,args --sort=-pcpu")
    rows = []
    for ln in out.splitlines()[1:]:
        if re.search(pat, ln, re.I):
            rows.append(ln)
    return rows

def match_pids(pat: str):
    pids = []
    out = sh("ps -eo pid,args")
    for ln in out.splitlines()[1:]:
        if re.search(pat, ln, re.I):
            try:
                pids.append(int(ln.split(None, 1)[0]))
            except Exception:
                pass
    return pids

CLK = os.sysconf("SC_CLK_TCK") or 100
try:
    NCPU = len(os.sched_getaffinity(0))
except Exception:
    NCPU = os.cpu_count() or 4

def read_tasks(pids):
    found = {{}}
    for pid in pids:
        tdir = "/proc/%d/task" % pid
        try:
            names = os.listdir(tdir)
        except OSError:
            continue
        for tid_s in names:
            path = "%s/%s" % (tdir, tid_s)
            try:
                comm = open(path + "/comm").read().strip()
                raw = open(path + "/stat").read()
            except OSError:
                continue
            rp = raw.rfind(")")
            rest = raw[rp + 2:].split()
            if len(rest) < 13:
                continue
            jiffies = int(rest[11]) + int(rest[12])
            found[(pid, int(tid_s))] = (jiffies, comm)
    return found

def top_threads_ps(n):
    out = sh("ps -eLo pid,lwp,pcpu,comm --sort=-pcpu")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return []
    return [lines[0]] + lines[1:n + 1]

print("=== host ===")
print(sh("uname -a").strip())
print("uptime:", sh("uptime").strip())
print("ncpu:", NCPU, "clk_tck:", CLK)
print()

prev = cpu_stat()
prev_tasks = read_tasks(match_pids(MATCH))
prev_t = time.monotonic()
time.sleep(0.25)
for i in range(1, SAMPLES + 1):
    cur = cpu_stat()
    di = cur[0] - prev[0]
    dt = cur[1] - prev[1]
    cpu_pct = (1.0 - (di / dt)) * 100.0 if dt > 0 else 0.0
    prev = cur
    now = time.monotonic()
    elapsed = max(0.001, now - prev_t)
    cur_tasks = read_tasks(match_pids(MATCH))
    total, avail, used = meminfo()
    print(f"=== sample {{i}}/{{SAMPLES}} ===")
    print("loadavg:", loadavg())
    print(f"cpu_approx: {{cpu_pct:.1f}}%  (ncpu={{NCPU}}, window={{elapsed:.2f}}s)")
    if total and used is not None and avail is not None:
        print(
            f"mem: used={{used/1024:.0f}}MiB "
            f"avail={{avail/1024:.0f}}MiB "
            f"total={{total/1024:.0f}}MiB "
            f"({{100.0*used/total:.1f}}% used)"
        )
    print("-- top CPU procesos --")
    for ln in top_ps(TOP_N):
        print(ln)
    print(f"-- match /{{MATCH}}/i --")
    hits = match_ps(MATCH)
    if hits:
        print("  PID %CPU %MEM   RSS     ELAPSED COMMAND")
        for ln in hits[:20]:
            print(ln)
    else:
        print("(ningún proceso matchea)")
    print("-- top CPU hilos (ps -eL, acumulado desde arranque) --")
    for ln in top_threads_ps(TOP_N):
        print(ln)
    print("-- hilos de procesos matcheados (delta % de 1 nucleo) --")
    ranked = []
    denom = float(CLK) * elapsed
    for key, (jif, comm) in cur_tasks.items():
        prev_j = prev_tasks.get(key, (jif, comm))[0]
        delta = jif - prev_j
        if delta < 0:
            delta = 0
        pct = 100.0 * delta / denom if denom else 0.0
        ranked.append((pct, key[0], key[1], comm))
    ranked.sort(reverse=True)
    print("  n_hilos:", len(ranked))
    print("  %CPU   PID    TID  COMM")
    for pct, pid, tid, comm in ranked[:16]:
        print(f"  {{pct:5.1f}}  {{pid:5d}}  {{tid:5d}}  {{comm}}")
    if not ranked:
        print("  (sin hilos de procesos matcheados)")
    prev_tasks = cur_tasks
    prev_t = now
    print("-- thermal (si existe) --")
    th = sh("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -n 3")
    if th.strip() and not th.startswith("ERR"):
        for raw in th.splitlines():
            try:
                print(f"  {{int(raw)/1000:.1f}} C")
            except Exception:
                print(" ", raw)
    else:
        print("  n/a")
    print()
    if i < SAMPLES:
        time.sleep(INTERVAL)

print("=== done ===")
PY
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Medir carga de procesos en la Raspberry Pi por SSH")
    parser.add_argument("--samples", type=int, default=6, help="Cantidad de muestras (default: 6)")
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Segundos entre muestras (default: 2)",
    )
    parser.add_argument(
        "--match",
        default="python|app\\.py|whisper|piper",
        help="Regex de procesos a destacar (default: python|app.py|whisper|piper)",
    )
    parser.add_argument("--top", type=int, default=12, help="Filas del top por CPU (default: 12)")
    args = parser.parse_args()

    host = env("PI_HOST", "192.168.0.136")
    user = env("PI_USER", "teo")
    password = env("PI_SSH_PASS")

    remote = build_remote_script(args.samples, args.interval, args.match, args.top)

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
            "Si la Pi está saturada (input overflow / Whisper), cerrá app.py en el escritorio "
            "o reiniciá la Pi y reintentá.\n"
        )
        return 1
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)

    print(f"# ssh {user}@{host}  samples={args.samples} interval={args.interval}s")
    try:
        _stdin, stdout, _stderr = client.exec_command(remote, get_pty=True)
        chan = stdout.channel
        chan.settimeout(1.0)
        while True:
            drained = False
            if chan.recv_ready():
                sys.stdout.buffer.write(chan.recv(8192))
                sys.stdout.flush()
                drained = True
            if chan.recv_stderr_ready():
                sys.stderr.buffer.write(chan.recv_stderr(8192))
                sys.stderr.flush()
                drained = True
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if not drained:
                time.sleep(0.12)
        return int(chan.recv_exit_status())
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
