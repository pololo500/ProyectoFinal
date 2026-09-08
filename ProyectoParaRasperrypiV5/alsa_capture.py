"""Captura persistente via arecord (ALSA hw:, 48 kHz S16_LE mono). Solo Linux en producción."""
from __future__ import annotations

import os
import re
import select
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

ENV_ALSA_CAPTURE_DEVICE = "ALSA_CAPTURE_DEVICE"

ALSA_RATE = 48000
ALSA_CHANNELS = 1
ALSA_FORMAT = "S16_LE"
ALSA_FRAMES_PER_READ = 960
ALSA_READ_BYTES = ALSA_FRAMES_PER_READ * 2  # S16_LE mono
ALSA_PERIOD_TIME_US = 20000
ALSA_BUFFER_TIME_US = 500000
PIPE_SIZE_PREFERRED = 1024 * 1024
PIPE_SIZE_FALLBACK = 64 * 1024


def fcntl_set_pipe_size(fd: int, size: int) -> int:
    import fcntl

    cmd = getattr(fcntl, "F_SETPIPE_SZ", 1031)
    fcntl.fcntl(fd, cmd, size)
    return size


def apply_pipe_size(fd: int) -> int:
    for size in (PIPE_SIZE_PREFERRED, PIPE_SIZE_FALLBACK):
        try:
            fcntl_set_pipe_size(fd, size)
            return size
        except OSError:
            continue
    return 0


def should_restart_arecord(
    *,
    n_read: int,
    poll_rc: int | None,
    stopping: bool,
) -> bool:
    if stopping:
        return False
    if poll_rc is not None:
        return True
    if n_read == 0:
        return True
    return False


def note_arecord_stderr_line(line: str, stats: dict[str, int]) -> None:
    low = (line or "").lower()
    if "overrun" in low:
        stats["overrun"] = int(stats.get("overrun", 0)) + 1
    if "busy" in low:
        stats["busy"] = int(stats.get("busy", 0)) + 1
    stripped = line.strip()
    if "period_time" in stripped:
        bits = stripped.split(":")
        if len(bits) >= 2:
            try:
                stats["period_time"] = int(bits[-1].strip().split()[0])
            except ValueError:
                pass
    if "buffer_time" in stripped:
        bits = stripped.split(":")
        if len(bits) >= 2:
            try:
                stats["buffer_time"] = int(bits[-1].strip().split()[0])
            except ValueError:
                pass


def build_arecord_argv(device: str) -> list[str]:
    return [
        "arecord",
        "-D",
        device,
        "-t",
        "raw",
        "-f",
        ALSA_FORMAT,
        "-c",
        str(ALSA_CHANNELS),
        "-r",
        str(ALSA_RATE),
        f"--period-time={ALSA_PERIOD_TIME_US}",
        f"--buffer-time={ALSA_BUFFER_TIME_US}",
        "-v",
    ]


_CARD_RE = re.compile(
    r"card\s+(?P<index>\d+):\s+(?P<id>\S+)\s+\[(?P<long>[^\]]+)\],\s+"
    r"device\s+(?P<dev>\d+):",
    re.MULTILINE,
)


@dataclass(frozen=True)
class AlsaCard:
    card_id: str
    card_index: int
    long_name: str
    device: int


def arecord_list_argv() -> list[str]:
    return ["arecord", "-l"]


def parse_arecord_cards(arecord_l: str) -> list[AlsaCard]:
    cards: list[AlsaCard] = []
    for match in _CARD_RE.finditer(arecord_l or ""):
        cards.append(
            AlsaCard(
                card_id=match.group("id"),
                card_index=int(match.group("index")),
                long_name=match.group("long"),
                device=int(match.group("dev")),
            )
        )
    return cards


def hw_device_string(card: AlsaCard) -> str:
    return f"hw:CARD={card.card_id},DEV={card.device}"


def match_card_for_sounddevice_name(
    sd_name: str,
    cards: list[AlsaCard],
) -> AlsaCard | None:
    name = (sd_name or "").lower()
    if not name or not cards:
        return None
    for card in cards:
        if card.long_name.lower() in name or card.card_id.lower() in name:
            return card
    return None


def resolve_alsa_capture_device(
    *,
    env: Mapping[str, str] | None,
    arecord_l: str,
    sounddevice_name: str,
) -> str:
    environ = env if env is not None else os.environ
    override = str(environ.get(ENV_ALSA_CAPTURE_DEVICE, "") or "").strip()
    if override:
        return override
    cards = parse_arecord_cards(arecord_l)
    matched = match_card_for_sounddevice_name(sounddevice_name, cards)
    if matched is None:
        raise ValueError(
            "No hay tarjeta ALSA de captura que coincida con "
            f"{sounddevice_name!r}. arecord -l:\n{arecord_l}"
        )
    return hw_device_string(matched)


def read_arecord_list() -> str:
    result = subprocess.run(
        arecord_list_argv(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def pcm_s16le_bytes_to_int16(block: bytes) -> np.ndarray:
    return np.frombuffer(block, dtype="<i2").copy()


def consume_raw_pcm(
    raw: bytes,
    muted: bool,
    audio_queue: Any,
    drop_hits: list[int],
    enqueue: Callable[..., None],
    leftover: bytes = b"",
) -> bytes:
    if muted:
        return b""
    buf = leftover + raw
    view = memoryview(buf)
    offset = 0
    while len(view) - offset >= ALSA_READ_BYTES:
        piece = bytes(view[offset : offset + ALSA_READ_BYTES])
        offset += ALSA_READ_BYTES
        enqueue(audio_queue, pcm_s16le_bytes_to_int16(piece), drop_hits)
    return bytes(view[offset:])


class AlsaCapture:
    def __init__(
        self,
        device: str,
        audio_queue: Any,
        drop_hits: list[int],
        stop_event: threading.Event,
        enqueue: Callable[..., None],
        speaker_busy: Callable[[], bool] | None = None,
        echo_until: list[float] | None = None,
    ) -> None:
        self.device = device
        self.audio_queue = audio_queue
        self.drop_hits = drop_hits
        self._stop_event = stop_event
        self._enqueue = enqueue
        self._speaker_busy = speaker_busy
        self._echo_until = echo_until if echo_until is not None else [0.0]
        self._muted = False
        self._proc: subprocess.Popen | None = None
        self._leftover = b""
        self._mute_lock = threading.Lock()
        self.overrun_hits = 0
        self.busy_hits = 0
        self.restarts = 0
        self.negotiated: dict[str, int] = {}
        self.pipe_size = 0
        self._drain_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._started = False

    def set_muted(self, muted: bool) -> None:
        new_muted = bool(muted)
        with self._mute_lock:
            was_muted = self._muted
            self._muted = new_muted
            if new_muted and not was_muted:
                self._leftover = b""

    def _should_enqueue(self) -> bool:
        if self._muted:
            return False
        if time.monotonic() < float(self._echo_until[0]):
            return False
        if self._speaker_busy is not None and self._speaker_busy():
            return False
        return True

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._started = True
            try:
                self._spawn()
                self._drain_thread = threading.Thread(
                    target=self._drain_loop, name="AlsaDrain", daemon=True
                )
                self._stderr_thread = threading.Thread(
                    target=self._stderr_loop, name="AlsaStderr", daemon=True
                )
                self._drain_thread.start()
                self._stderr_thread.start()
            except Exception:
                self._started = False
                raise

    def stop(self) -> None:
        self._stop_event.set()
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stderr is not None:
                    proc.stderr.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        current = threading.current_thread()
        for thread in (self._drain_thread, self._stderr_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1.0)
        proc = self._proc
        if proc is not None:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stderr is not None:
                    proc.stderr.close()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            self._proc = None

    def _spawn(self) -> None:
        proc = subprocess.Popen(
            build_arecord_argv(self.device),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._proc = proc
        if proc.stdout is not None:
            try:
                self.pipe_size = apply_pipe_size(proc.stdout.fileno())
            except Exception:
                self.pipe_size = 0

    def _restart(self) -> None:
        if self._stop_event.is_set():
            return
        old = self._proc
        if old is not None:
            try:
                old.kill()
            except Exception:
                pass
            try:
                old.wait(timeout=0.5)
            except Exception:
                pass
            try:
                if old.stdout is not None:
                    old.stdout.close()
            except Exception:
                pass
            try:
                if old.stderr is not None:
                    old.stderr.close()
            except Exception:
                pass
            if self._proc is old:
                self._proc = None
        self.restarts += 1
        self._leftover = b""
        time.sleep(0.2)
        if self._stop_event.is_set():
            return
        self._spawn()
        if self._stop_event.is_set():
            return
        if self._stderr_thread is None or not self._stderr_thread.is_alive():
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop, name="AlsaStderr", daemon=True
            )
            self._stderr_thread.start()

    def _read_chunk(self, proc: subprocess.Popen) -> bytes | None:
        """bytes = datos o EOF; None = select timeout (proceso vivo)."""
        stdout = proc.stdout
        if stdout is None:
            return b""
        try:
            ready, _, _ = select.select([stdout], [], [], 1.0)
        except (OSError, ValueError, TypeError):
            ready = [stdout]
        if not ready:
            return None
        try:
            return os.read(stdout.fileno(), ALSA_READ_BYTES)
        except Exception:
            return b""

    def _drain_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                proc = self._proc
                if proc is None:
                    self._restart()
                    continue
                chunk = self._read_chunk(proc)
                poll_rc = proc.poll()
                if chunk is None:
                    if should_restart_arecord(
                        n_read=-1, poll_rc=poll_rc, stopping=self._stop_event.is_set()
                    ):
                        self._restart()
                    continue
                if should_restart_arecord(
                    n_read=len(chunk),
                    poll_rc=poll_rc,
                    stopping=self._stop_event.is_set(),
                ):
                    self._restart()
                    continue
                with self._mute_lock:
                    muted = not self._should_enqueue()
                    self._leftover = consume_raw_pcm(
                        chunk,
                        muted,
                        self.audio_queue,
                        self.drop_hits,
                        self._enqueue,
                        leftover=self._leftover,
                    )
            except OSError:
                if self._stop_event.wait(0.2):
                    return

    def _stderr_loop(self) -> None:
        while not self._stop_event.is_set():
            proc = self._proc
            if proc is None or proc.stderr is None:
                time.sleep(0.05)
                continue
            try:
                line = proc.stderr.readline()
            except (OSError, ValueError):
                time.sleep(0.05)
                continue
            if not line:
                time.sleep(0.05)
                continue
            text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
            stats = {
                "overrun": 0,
                "busy": 0,
                "period_time": int(self.negotiated.get("period_time", 0)),
                "buffer_time": int(self.negotiated.get("buffer_time", 0)),
            }
            note_arecord_stderr_line(text, stats)
            self.overrun_hits += int(stats["overrun"])
            self.busy_hits += int(stats["busy"])
            if stats.get("period_time"):
                self.negotiated["period_time"] = stats["period_time"]
            if stats.get("buffer_time"):
                self.negotiated["buffer_time"] = stats["buffer_time"]
