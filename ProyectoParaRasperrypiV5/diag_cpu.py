"""CPU por proceso e hilo (Linux /proc). Corrélo en la Pi con Teo en marcha.

    python diag_cpu.py
    python diag_cpu.py --seconds 3 --watch
    python diag_cpu.py --all
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

PROC = Path("/proc")


def parse_stat_line(line: str) -> dict[str, Any]:
    text = (line or "").strip()
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right < left:
        raise ValueError("stat sin comm")
    pid = int(text[:left].strip())
    comm = text[left + 1 : right]
    rest = text[right + 1 :].split()
    utime = int(rest[11])
    stime = int(rest[12])
    rss_pages = int(rest[21]) if len(rest) > 21 else 0
    return {
        "pid": pid,
        "comm": comm,
        "utime": utime,
        "stime": stime,
        "ticks": utime + stime,
        "rss_pages": rss_pages,
    }


def cpu_percent(delta_ticks: int, interval_s: float, hz: int) -> float:
    if interval_s <= 0 or hz <= 0:
        return 0.0
    return 100.0 * float(delta_ticks) / (float(hz) * interval_s)


def rank_by_cpu(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: float(row.get("cpu") or 0.0), reverse=True)


def _clk_tck() -> int:
    try:
        return int(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, OSError, ValueError):
        return 100


def _page_size() -> int:
    try:
        return int(os.sysconf("SC_PAGESIZE"))
    except (AttributeError, OSError, ValueError):
        return 4096


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cmdline(pid: int) -> str:
    raw = _read_text(PROC / str(pid) / "cmdline")
    return raw.replace("\x00", " ").strip()


def _thread_name(pid: int, tid: int) -> str:
    name = _read_text(PROC / str(pid) / "task" / str(tid) / "comm").strip()
    return name or str(tid)


def _list_pids() -> list[int]:
    out: list[int] = []
    try:
        for entry in PROC.iterdir():
            if entry.name.isdigit():
                out.append(int(entry.name))
    except OSError:
        return []
    return out


def _list_tids(pid: int) -> list[int]:
    task = PROC / str(pid) / "task"
    try:
        return [int(p.name) for p in task.iterdir() if p.name.isdigit()]
    except OSError:
        return []


def snapshot_pid(pid: int) -> dict[str, Any] | None:
    stat = _read_text(PROC / str(pid) / "stat")
    if not stat:
        return None
    try:
        parsed = parse_stat_line(stat)
    except (ValueError, IndexError):
        return None
    threads: dict[int, dict[str, Any]] = {}
    for tid in _list_tids(pid):
        tstat = _read_text(PROC / str(pid) / "task" / str(tid) / "stat")
        if not tstat:
            continue
        try:
            tparsed = parse_stat_line(tstat)
        except (ValueError, IndexError):
            continue
        threads[tid] = {
            "tid": tid,
            "name": _thread_name(pid, tid),
            "ticks": tparsed["ticks"],
        }
    parsed["cmdline"] = _cmdline(pid)
    parsed["threads"] = threads
    parsed["rss_mb"] = parsed["rss_pages"] * _page_size() / (1024 * 1024)
    return parsed


def _interesting(cmdline: str, comm: str) -> bool:
    blob = f"{cmdline} {comm}".lower()
    return any(
        key in blob
        for key in (
            "app.py",
            "llmchild",
            "whisperchild",
            "proyectopara",
            "proyectofinal",
            "llama",
        )
    )


def sample(
    seconds: float,
    *,
    all_procs: bool = False,
    pids: list[int] | None = None,
) -> dict[str, Any]:
    hz = _clk_tck()
    if pids:
        wanted = list(pids)
    else:
        wanted = []
        for pid in _list_pids():
            cmd = _cmdline(pid)
            stat_text = _read_text(PROC / str(pid) / "stat")
            if not stat_text:
                continue
            try:
                comm = parse_stat_line(stat_text)["comm"]
            except (ValueError, IndexError):
                comm = ""
            if all_procs or _interesting(cmd, comm):
                wanted.append(pid)
        if not wanted:
            wanted = _list_pids()

    first: dict[int, dict[str, Any]] = {}
    for pid in wanted:
        snap = snapshot_pid(pid)
        if snap:
            first[pid] = snap
    time.sleep(max(0.2, seconds))
    rows: list[dict[str, Any]] = []
    thread_rows: list[dict[str, Any]] = []
    for pid, before in first.items():
        after = snapshot_pid(pid)
        if after is None:
            continue
        delta = after["ticks"] - before["ticks"]
        cpu = cpu_percent(delta, seconds, hz)
        label = after["cmdline"] or after["comm"]
        rows.append(
            {
                "pid": pid,
                "comm": after["comm"],
                "label": label[:90],
                "cpu": cpu,
                "rss_mb": after["rss_mb"],
                "nthreads": len(after["threads"]),
            }
        )
        before_threads = before["threads"]
        for tid, after_t in after["threads"].items():
            prev = before_threads.get(tid)
            if prev is None:
                continue
            tdelta = after_t["ticks"] - prev["ticks"]
            thread_rows.append(
                {
                    "pid": pid,
                    "tid": tid,
                    "name": after_t["name"],
                    "cpu": cpu_percent(tdelta, seconds, hz),
                    "proc": (after["cmdline"] or after["comm"])[:60],
                }
            )
    load = _read_text(PROC / "loadavg").split()[:3]
    return {
        "seconds": seconds,
        "ncpu": os.cpu_count() or 1,
        "load": load,
        "procs": rank_by_cpu(rows),
        "threads": rank_by_cpu(thread_rows),
    }


def format_report(data: dict[str, Any], top: int = 15) -> str:
    lines = [
        f"muestra={data['seconds']:.1f}s  núcleos={data['ncpu']}  load={' '.join(data['load'])}",
        "",
        "PROCESOS (CPU % de un núcleo; 400% = 4 núcleos a full)",
        f"{'CPU%':>8} {'RSS_MB':>8} {'Hilos':>6} {'PID':>7}  comando",
    ]
    for row in data["procs"][:top]:
        lines.append(
            f"{row['cpu']:8.1f} {row['rss_mb']:8.0f} {row['nthreads']:6d} {row['pid']:7d}  {row['label']}"
        )
    lines += [
        "",
        "HILOS (el nombre es el de pthread: AudioWorker, LlmChild, piper, …)",
        f"{'CPU%':>8} {'PID':>7} {'TID':>7}  hilo  proceso",
    ]
    for row in data["threads"][:top]:
        lines.append(
            f"{row['cpu']:8.1f} {row['pid']:7d} {row['tid']:7d}  {row['name']:<18} {row['proc']}"
        )
    if data["procs"]:
        heavy = data["procs"][0]
        lines += [
            "",
            f"Más pesado: PID {heavy['pid']}  {heavy['cpu']:.0f}% CPU  {heavy['rss_mb']:.0f} MB  {heavy['label']}",
        ]
    if data["threads"]:
        ht = data["threads"][0]
        lines.append(
            f"Hilo más pesado: {ht['name']}  tid={ht['tid']}  {ht['cpu']:.0f}%  (pid {ht['pid']})"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qué proceso/hilo come CPU en Teo")
    parser.add_argument("--seconds", type=float, default=2.0, help="duración de la muestra")
    parser.add_argument("--watch", action="store_true", help="repetir hasta Ctrl+C")
    parser.add_argument("--all", action="store_true", help="todos los procesos, no solo Teo")
    parser.add_argument("--pid", type=int, action="append", help="PID extra (se puede repetir)")
    args = parser.parse_args(argv)
    if os.name != "posix" or not PROC.exists():
        print("Este script lee /proc: corrélo en la Raspberry Pi.", file=sys.stderr)
        return 2
    try:
        while True:
            data = sample(args.seconds, all_procs=args.all, pids=args.pid)
            print(format_report(data))
            print()
            if not args.watch:
                return 0
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
