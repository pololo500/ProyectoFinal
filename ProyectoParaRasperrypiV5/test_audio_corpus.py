"""Tests de corpus de audio: nombre del archivo = frase hablada.

  python test_audio_corpus.py              NLU + STT de los clips que existan
  python test_audio_corpus.py --nlu-only   Solo clasificar el texto del manifiesto
  python test_audio_corpus.py --generate   Crear MP3 TTS (voz es-AR) si faltan

El STT usa faster-whisper en español, igual que el peluche.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from unittest.mock import MagicMock

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import IntentDispatcher

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
CORPUS = ROOT / "tests" / "audio_frases"
USER_RECORDINGS = REPO_ROOT / "ArchivosDeAudioParaPruebas"
MANIFEST_PATH = CORPUS / "manifest.json"
TTS_VOICE = "es-AR-ElenaNeural"
AUDIO_EXTS = (".m4a", ".wav", ".mp3", ".ogg", ".aac", ".flac")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_phrase(text: str) -> str:
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def phrases_match(expected: str, got: str, min_ratio: float = 0.55) -> bool:
    exp = normalize_phrase(expected)
    got_n = normalize_phrase(got)
    if not exp:
        return not got_n
    if exp in got_n or got_n in exp:
        return True
    exp_tok = set(exp.split())
    got_tok = set(got_n.split())
    if not exp_tok:
        return False
    overlap = len(exp_tok & got_tok) / len(exp_tok)
    return overlap >= min_ratio


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _stem_key(name: str) -> str:
    return normalize_phrase(Path(name).stem)


def _index_audio_dirs(dirs: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for folder in dirs:
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTS:
                continue
            key = _stem_key(path.name)
            if not key:
                continue
            if key not in index or folder == USER_RECORDINGS:
                index[key] = path
    return index


def clip_audio_path(clip: dict, index: dict[str, Path] | None = None) -> Path | None:
    if index is None:
        index = _index_audio_dirs([USER_RECORDINGS, CORPUS])
    keys = [_stem_key(clip.get("file", ""))]
    for alias in clip.get("aliases") or []:
        keys.append(_stem_key(alias))
    user_hit = None
    any_hit = None
    user_dir = USER_RECORDINGS.resolve() if USER_RECORDINGS.is_dir() else None
    for key in keys:
        if not key or key not in index:
            continue
        path = index[key]
        if any_hit is None:
            any_hit = path
        if user_dir is not None and path.resolve().parent == user_dir:
            user_hit = path
            break
    return user_hit or any_hit


async def _tts_edge(text: str, dest: Path, voice: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(dest))


def _tts_windows_sapi(text: str, dest: Path) -> None:
    """WAV 16 kHz vía voces de Windows (no necesita edge-tts)."""
    wav_path = dest.with_suffix(".wav")
    safe_text = text.replace("'", "")
    safe_wav = str(wav_path).replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo }; "
        "$es = $voices | Where-Object { $_.Culture.Name -like 'es*' } | Select-Object -First 1; "
        "if ($es) { $s.SelectVoice($es.Name) }; "
        "$s.Rate = -2; "
        f"$s.SetOutputToWaveFile('{safe_wav}'); "
        f"$s.Speak('{safe_text}'); "
        "$s.Dispose();"
    )
    import subprocess

    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
    )
    if dest.suffix.lower() != ".wav" and dest.exists() and dest.stat().st_size == 0:
        dest.unlink()


def generate_tts(clips: list[dict], force: bool = False) -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    use_edge = True
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        use_edge = False
        print("edge-tts no está instalado; uso la voz de Windows.")

    async def _run_edge() -> int:
        created = 0
        for clip in clips:
            dest = CORPUS / clip["file"]
            if dest.exists() and not force:
                continue
            print(f"  TTS -> {dest.name}")
            await _tts_edge(clip["text"], dest, TTS_VOICE)
            created += 1
        return created

    if use_edge:
        return asyncio.run(_run_edge())

    created = 0
    for clip in clips:
        dest = CORPUS / clip["file"]
        wav_dest = dest.with_suffix(".wav")
        if (wav_dest.exists() or (dest.exists() and dest.stat().st_size > 0)) and not force:
            continue
        print(f"  TTS (Windows) -> {wav_dest.name}")
        _tts_windows_sapi(clip["text"], dest)
        created += 1
    return created


def transcribe_file(model: object, path: Path) -> str:
    segments, _info = model.transcribe(
        str(path),
        language="es",
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    parts = [seg.text.strip() for seg in segments if getattr(seg, "text", "").strip()]
    return " ".join(parts).strip()


def load_whisper():
    from faster_whisper import WhisperModel

    size = (os.environ.get("WHISPER_MODEL") or "small").strip() or "small"
    print(f"Cargando Whisper {size} (cpu/int8)...")
    return WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)


def run_nlu(dispatcher: IntentDispatcher, clips: list[dict]) -> int:
    print("\n=== NLU (texto del manifiesto) ===")
    fail = 0
    checked = 0
    for clip in clips:
        expected = clip.get("intent")
        if expected is None:
            continue
        checked += 1
        result = dispatcher.dispatch(clip["text"])
        got = result.get("intent_name", "unknown")
        ok = got == expected
        if not ok:
            fail += 1
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {clip['text']!r:45} intent={expected:22} got={got}")
    print(f"NLU: {checked - fail}/{checked} ok")
    return fail


def run_stt(dispatcher: IntentDispatcher, clips: list[dict]) -> int:
    print("\n=== STT + NLU (archivos de audio) ===")
    index = _index_audio_dirs([USER_RECORDINGS, CORPUS])
    if USER_RECORDINGS.is_dir():
        print(f"Grabaciones: {USER_RECORDINGS}")
    present = [(c, clip_audio_path(c, index)) for c in clips]
    missing = [c["file"] for c, p in present if p is None]
    if missing:
        print("Sin audio aún (grabalos o corré --generate):")
        for name in missing:
            print(f"  - {name}")
    to_run = [(c, p) for c, p in present if p is not None]
    if not to_run:
        print("No hay clips para transcribir.")
        return 0

    model = load_whisper()
    fail = 0
    for clip, path in to_run:
        got_text = transcribe_file(model, path)
        stt_ok = phrases_match(clip["text"], got_text)
        expected_intent = clip.get("intent")
        intent_ok = True
        got_intent = ""
        if expected_intent is not None:
            got_intent = dispatcher.dispatch(got_text or clip["text"]).get("intent_name", "unknown")
            intent_ok = got_intent == expected_intent
        ok = stt_ok and intent_ok
        if not ok:
            fail += 1
        mark = "OK" if ok else "FAIL"
        extra = f" intent {expected_intent}->{got_intent}" if expected_intent else " (turno de juego, solo STT)"
        print(f"  [{mark}] {path.name}")
        print(f"         esperado={clip['text']!r}  whisper={got_text!r}{extra}")
    print(f"Audio: {len(to_run) - fail}/{len(to_run)} ok")
    return fail


def main() -> int:
    parser = argparse.ArgumentParser(description="Corpus de audio TEO")
    parser.add_argument("--nlu-only", action="store_true")
    parser.add_argument("--generate", action="store_true", help="Generar MP3 TTS de las frases core")
    parser.add_argument("--force", action="store_true", help="Pisar TTS existentes")
    args = parser.parse_args()

    manifest = load_manifest()
    clips = manifest["clips"]

    if args.generate:
        print("Generando TTS (edge-tts, es-AR)...")
        n = generate_tts(clips, force=args.force)
        print(f"Creados {n} archivos en {CORPUS}")

    print("Cargando IntentDispatcher...")
    dispatcher = IntentDispatcher.from_file(ROOT / "intent_rules.json")
    extra = manifest.get("record_also") or []
    fail = run_nlu(dispatcher, clips)
    if not args.nlu_only:
        fail += run_stt(dispatcher, clips + extra)

    if fail:
        print(f"\nFALLA: {fail} chequeo(s)")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
