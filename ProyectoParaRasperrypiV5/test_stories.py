"""Tests de cuentos (validación, biblioteca, motor) sin hardware ni LLM."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from story_engine import StoryEngine
from story_library import StoryLibrary, ingest_pdf
from story_validate import MIN_WORDS, split_for_speech, validate_children_story

PASS = 0
FAIL = 0


def ok(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  ->  {detail}" if detail else ""))


def _story_text(title_line: str = "El sapo valiente") -> str:
    body = (
        "Había una vez un sapo que vivía junto al arroyo. Un día dijo que quería "
        "cruzar el puente para ver a sus amigos del otro lado del agua. Entonces "
        "preguntó al viento si podía ayudarlo a saltar sin caerse. El viento sopló "
        "despacio y el sapo saltó con mucho cuidado sobre las piedras. Al otro lado "
        "lo esperaba una rana que le preguntó si había tenido un poquito de miedo. "
        "El sapo dijo que sí, un poquito, pero que juntos todo era más fácil. "
        "Capítulo dos: volvieron a casa cantando bajito y se durmieron bajo la luna "
        "con la panza llena de cuentos y de abrazos."
    )
    return f"{title_line}\n\n{body}"


def test_validate_accepts_short_story() -> None:
    result = validate_children_story(_story_text())
    ok("cuento narrativo se acepta", result.ok, result.reason)


def test_validate_rejects_too_short() -> None:
    result = validate_children_story("Había una vez un gato.")
    ok("texto corto se rechaza", not result.ok)
    ok("motivo menciona largo", "palabras" in result.reason.lower() or "corto" in result.reason.lower())


def test_validate_rejects_invoice() -> None:
    invoice = (
        "FACTURA A  CUIT 20-12345678-9  IVA responsable. Total a pagar $15000. "
        "http://pagos.ejemplo.com copyright 2024 pagina 1 de 3. "
        "Item 1 2000 item 2 3000 item 3 4000 item 4 6000."
    )
    result = validate_children_story(invoice)
    ok("factura se rechaza", not result.ok, result.reason)


def test_validate_rejects_blocklist() -> None:
    dirty = _story_text() + " El lobo miraba pornografía en la computadora."
    result = validate_children_story(dirty)
    ok("lista de bloqueo rechaza", not result.ok)
    ok("motivo no cita la palabra", "porn" not in result.reason.lower())


def test_split_paragraphs() -> None:
    text = "Uno. Dos. Tres.\n\nCuatro. Cinco. Seis. Siete."
    chunks = split_for_speech(text, max_chars=40)
    ok("split produce varios bloques", len(chunks) >= 2, f"chunks={chunks}")


def test_library_save_list_delete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        listed = lib.list_stories()
        ok("guarda y lista", len(listed) == 1 and listed[0].title == "El sapo")
        loaded = lib.load_text(rec.id)
        ok("carga texto", loaded is not None and "sapo" in loaded.lower())
        ok("borra", lib.delete(rec.id) and lib.list_stories() == [])


def test_ingest_rejects_non_pdf() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = ingest_pdf(b"not a pdf", "nota.txt", stories_dir=Path(tmp))
        ok("no pdf se rechaza", result["status"] == "rejected")


def test_ingest_rejects_oversize() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        huge = b"%PDF" + b"x" * (8 * 1024 * 1024 + 10)
        result = ingest_pdf(huge, "grande.pdf", stories_dir=Path(tmp))
        ok("pdf enorme se rechaza", result["status"] == "rejected")


def test_engine_zero_stories() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = StoryEngine(StoryLibrary(Path(tmp)))
        out = engine.process_or_passthrough(
            "contame un cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        ok("sin cuentos avisa al adulto", "mamá" in out["response"].lower() or "papá" in out["response"].lower())
        ok("sigue idle", not engine.is_active)


def test_engine_one_story_yes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("El sapo valiente", _story_text())
        engine = StoryEngine(lib)
        out = engine.process_or_passthrough(
            "contame un cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        ok("un cuento ofrece título", "sapo" in out["response"].lower() and engine.is_active)
        out2 = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        ok("sí dispara lectura", bool(out2.get("story_chunk")), str(out2.keys()))
        ok("quedó en check-in o reflexión", engine.state in ("checking_in", "reflecting"), engine.state)


def test_engine_pick_title() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("Caperucita", _story_text("Caperucita"))
        lib.save_story("El sapo valiente", _story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "un cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        out = engine.process_or_passthrough("el sapo", {"intent_name": "unknown", "response": ""})
        ok("elige por título", "sapo" in out["response"].lower() or bool(out.get("story_chunk")))
        chunk = str(out.get("story_chunk") or "")
        ok("leyó el sapo", "sapo" in chunk.lower() or "sapo" in out["response"].lower())


def test_engine_basta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("El sapo valiente", _story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        out = engine.process_or_passthrough("basta", {"intent_name": "unknown", "response": ""})
        ok("basta cancela", not engine.is_active)
        ok("cierre corto", "después" in out["response"].lower() or "paro" in out["response"].lower() or "listo" in out["response"].lower())


def test_engine_cualquiera() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("A uno", _story_text("Uno"))
        lib.save_story("B dos", _story_text("Dos"))
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        out = engine.process_or_passthrough("cualquiera", {"intent_name": "unknown", "response": ""})
        ok("cualquiera lee uno", bool(out.get("story_chunk")))


def test_engine_delete_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo valiente", _story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        lib.delete(rec.id)
        out = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        ok("archivo borrado se avisa", "no está" in out["response"].lower() or "ya no" in out["response"].lower())


def test_engine_checkin_and_silence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("El sapo valiente", _story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        first = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        if engine.state == "checking_in":
            ok("primer bloque pide seguimos", first.get("story_checkin") == "¿Seguimos?")
            engine.advance_silence()
            ok("silencio avanza", engine.state in ("checking_in", "reflecting"), engine.state)
            stop = engine.process_or_passthrough("basta", {"intent_name": "unknown", "response": ""})
            ok("basta en check-in para", not engine.is_active)
            ok("cierre", "paramos" in stop["response"].lower() or "listo" in stop["response"].lower())
        else:
            ok("cuento corto va a reflexión", engine.state == "reflecting" and bool(first.get("story_need_reflection")))
            digest = first.get("story_digest") or ""
            ok("digest acotado", 0 < len(digest) <= 401)


def test_engine_last_chunk_reflection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        lib.save_story("Corto", _story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        first = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        last = first
        guard = 0
        while engine.state == "checking_in" and guard < 20:
            last = engine.advance_silence()
            guard += 1
        ok("termina en reflecting", engine.state == "reflecting")
        ok("pide reflexión", bool(last.get("story_need_reflection")) or engine.state == "reflecting")
        digest = last.get("story_digest") or engine._digest
        ok("digest no vacío", bool(digest))
        ans = engine.process_or_passthrough("me gustó el sapo", {"intent_name": "unknown", "response": ""})
        ok("respuesta de reflexión", ans.get("intent_name") == "story_reflect_answer")
        ok("después espera otro", engine.state == "awaiting_more")


def test_digest_limit() -> None:
    from story_engine import make_digest
    long = "palabra " * 200
    d = make_digest(long, 400)
    ok("digest respeta límite", len(d) <= 401)


def test_min_words_constant() -> None:
    ok("mínimo 80 palabras", MIN_WORDS == 80)


if __name__ == "__main__":
    print("\n=== CUENTOS ===")
    test_validate_accepts_short_story()
    test_validate_rejects_too_short()
    test_validate_rejects_invoice()
    test_validate_rejects_blocklist()
    test_split_paragraphs()
    test_library_save_list_delete()
    test_ingest_rejects_non_pdf()
    test_ingest_rejects_oversize()
    test_engine_zero_stories()
    test_engine_one_story_yes()
    test_engine_pick_title()
    test_engine_basta()
    test_engine_cualquiera()
    test_engine_delete_missing()
    test_engine_checkin_and_silence()
    test_engine_last_chunk_reflection()
    test_digest_limit()
    test_min_words_constant()
    print(f"\nPASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)
