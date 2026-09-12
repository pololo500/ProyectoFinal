"""Tests de cuentos (validación, biblioteca, motor) sin hardware ni LLM."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import re

from story_engine import StoryEngine
from story_library import StoryLibrary, ingest_pdf
from story_validate import (
    CHECKIN_AFTER_WORDS,
    MIN_WORDS,
    sentence_prefetch_plan,
    split_for_speech,
    split_into_sentences,
    validate_children_story,
)

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


def _long_story_text() -> str:
    sents = [
        f"El sapo saltó la piedra número {i} y saludó a sus amigos del arroyo."
        for i in range(1, 31)
    ]
    return "El sapo valiente\n\n" + " ".join(sents)


def test_split_paragraphs() -> None:
    from story_validate import _word_count

    ok("check-in a las 100 palabras", CHECKIN_AFTER_WORDS == 100, str(CHECKIN_AFTER_WORDS))

    sents = split_into_sentences("Había un sapo. Saltó la piedra. Saludó a sus amigos.")
    ok("parte en oraciones", sents == [
        "Había un sapo.",
        "Saltó la piedra.",
        "Saludó a sus amigos.",
    ], str(sents))
    plan = sentence_prefetch_plan(sents)
    ok(
        "prefetch de la siguiente oración",
        plan == [
            ("Había un sapo.", "Saltó la piedra."),
            ("Saltó la piedra.", "Saludó a sus amigos."),
            ("Saludó a sus amigos.", None),
        ],
        str(plan),
    )

    short = "Uno. Dos. Tres.\n\nCuatro. Cinco. Seis. Siete."
    short_chunks = split_for_speech(short)
    ok("cuento corto un solo bloque", len(short_chunks) == 1, f"chunks={short_chunks}")

    many_paras = "\n\n".join(
        f"Había un sapo muy valiente en el arroyo {i}." for i in range(1, 12)
    )
    packed = split_for_speech(many_paras)
    ok(
        "párrafos cortos no hacen un check-in cada uno",
        len(packed) <= 2,
        f"n={len(packed)} chunks={packed}",
    )

    long = _long_story_text()
    chunks = split_for_speech(long)
    ok("cuento largo tiene más de un bloque", len(chunks) >= 2, f"n={len(chunks)}")
    for i, chunk in enumerate(chunks[:-1]):
        ok(
            f"bloque {i} termina en punto",
            bool(re.search(r"[.!?]\s*$", chunk)),
            chunk[-20:],
        )
        ok(
            f"bloque {i} llega a {CHECKIN_AFTER_WORDS} palabras",
            _word_count(chunk) >= CHECKIN_AFTER_WORDS,
            str(_word_count(chunk)),
        )


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


@contextmanager
def _fake_pdf_text(text: str):
    import story_library as sl

    original = sl.extract_pdf_text
    sl.extract_pdf_text = lambda _b: (text, 1, None)
    try:
        yield
    finally:
        sl.extract_pdf_text = original


@contextmanager
def _api_stories(stories_dir: Path):
    import api_server

    prev_dir = api_server.STORIES_DIR
    prev_token = api_server.robot_state.pairing_token
    api_server.STORIES_DIR = Path(stories_dir)
    api_server.robot_state.pairing_token = ""
    httpd = HTTPServer(("127.0.0.1", 0), api_server.ApiRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        api_server.STORIES_DIR = prev_dir
        api_server.robot_state.pairing_token = prev_token


def _http_json(
    method: str,
    url: str,
    body: dict | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    hdrs = dict(headers or {})
    data: bytes | None = None
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(body, bytes):
        data = body
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        return exc.code, payload


def test_ingest_title_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _fake_pdf_text(_story_text()):
            result = ingest_pdf(
                b"%PDF-fake",
                "archivo.pdf",
                stories_dir=Path(tmp),
                title="  El sapo feliz  ",
            )
        ok("ingest con título override queda ready", result.get("status") == "ready", str(result))
        ok("ingest usa el título pedido", result.get("title") == "El sapo feliz", str(result.get("title")))


def test_ingest_title_empty_falls_back() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _fake_pdf_text(_story_text()):
            result = ingest_pdf(
                b"%PDF-fake",
                "archivo.pdf",
                stories_dir=Path(tmp),
                title="   ",
            )
        ok(
            "título vacío cae al texto/archivo",
            result.get("status") == "ready" and result.get("title") == "El sapo valiente",
            str(result.get("title")),
        )


def test_ingest_title_truncated() -> None:
    long_title = "A" * 81
    with tempfile.TemporaryDirectory() as tmp:
        with _fake_pdf_text(_story_text()):
            result = ingest_pdf(
                b"%PDF-fake",
                "archivo.pdf",
                stories_dir=Path(tmp),
                title=long_title,
            )
        ok("título largo se recorta a 80", result.get("title") == "A" * 80, str(result.get("title")))


def test_update_story_title() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("Viejo título", _story_text())
        result = lib.update_story(rec.id, title="  Nuevo título  ")
        ok("update título ok", isinstance(result, dict) and result.get("status") == "ok", str(result))
        ok("update título cambia el nombre", result.get("title") == "Nuevo título", str(result))
        stored = lib.get(rec.id)
        ok("json guarda el título nuevo", stored is not None and stored.title == "Nuevo título")


def test_update_story_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        new_text = _story_text("La rana amiga")
        result = lib.update_story(rec.id, text=new_text)
        ok("update texto ok", isinstance(result, dict) and result.get("status") == "ok", str(result))
        loaded = lib.load_text(rec.id)
        ok("texto nuevo persistido", loaded == new_text, str(loaded)[:40] if loaded else "None")
        expected_words = len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", new_text))
        ok("word_count se recalcula", result.get("word_count") == expected_words, str(result.get("word_count")))


def test_update_story_keeps_id_and_created_at() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        result = lib.update_story(rec.id, title="Otro nombre", text=_story_text("Otro"))
        ok("update no cambia id", result.get("id") == rec.id, str(result))
        stored = lib.get(rec.id)
        ok("created_at se conserva", stored is not None and stored.created_at == rec.created_at, str(stored))
        ok("sigue existiendo un solo json", len(list(Path(tmp).glob("*.json"))) == 1)


def test_update_story_rejects_invalid_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        original = lib.load_text(rec.id)
        result = lib.update_story(rec.id, text="Había una vez un gato.")
        ok("texto inválido rejected", result.get("status") == "rejected", str(result))
        ok("rejected trae reason", bool(result.get("reason")), str(result))
        ok("texto original intacto", lib.load_text(rec.id) == original)
        ok("título original intacto", lib.get(rec.id) is not None and lib.get(rec.id).title == "El sapo")


def test_update_story_missing_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        result = lib.update_story("no-existe", title="Hola")
        ok("update de id inexistente es None", result is None, str(result))


def test_http_get_story_and_404() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        with _api_stories(Path(tmp)) as base:
            status, payload = _http_json("GET", f"{base}/api/stories/{rec.id}")
            ok("GET cuento 200", status == 200, str(status))
            ok("GET incluye texto", payload.get("text") == _story_text(), str(payload.keys()))
            ok("GET incluye id y título", payload.get("id") == rec.id and payload.get("title") == "El sapo")
            status404, err = _http_json("GET", f"{base}/api/stories/no-existe")
            ok("GET 404 status", status404 == 404, str(status404))
            ok("GET 404 mensaje", err.get("error") == "Cuento no encontrado", str(err))
            status_list, listed = _http_json("GET", f"{base}/api/stories")
            ok("GET lista no se rompe", status_list == 200 and "stories" in listed, str(listed)[:80])


def test_http_put_story_and_404() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lib = StoryLibrary(Path(tmp))
        rec = lib.save_story("El sapo", _story_text())
        with _api_stories(Path(tmp)) as base:
            url = f"{base}/api/stories/{rec.id}"
            status, payload = _http_json("PUT", url, {"title": "Sapo editado"})
            ok("PUT título 200", status == 200 and payload.get("status") == "ok", str(payload))
            ok("PUT no cambia id", payload.get("id") == rec.id, str(payload))
            ok("PUT devuelve título", payload.get("title") == "Sapo editado", str(payload))

            bad_status, bad = _http_json("PUT", url, {"text": "Había una vez un gato."})
            ok(
                "PUT texto inválido 200 rejected",
                bad_status == 200 and bad.get("status") == "rejected",
                str(bad),
            )
            ok("PUT rejected trae reason", bool(bad.get("reason")), str(bad))

            missing_status, missing = _http_json("PUT", f"{base}/api/stories/no-existe", {"title": "X"})
            ok("PUT 404 status", missing_status == 404, str(missing_status))
            ok("PUT 404 mensaje", missing.get("error") == "Cuento no encontrado", str(missing))

            empty_status, empty = _http_json("PUT", url, {})
            ok("PUT sin campos 400", empty_status == 400, str(empty))
            ok("PUT 400 trae error", "error" in empty, str(empty))

            invalid_status, invalid = _http_json(
                "PUT",
                url,
                b"{no json",
                headers={"Content-Type": "application/json"},
            )
            ok("PUT JSON inválido 400", invalid_status == 400, str(invalid))


def test_http_upload_story_title_header() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with _fake_pdf_text(_story_text()):
            with _api_stories(Path(tmp)) as base:
                status, payload = _http_json(
                    "POST",
                    f"{base}/api/stories/upload",
                    b"%PDF-fake",
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Filename": "archivo.pdf",
                        "X-Story-Title": "El%20Sapo%20Feliz",
                    },
                )
        ok("upload header 200 ready", status == 200 and payload.get("status") == "ready", str(payload))
        ok("upload decodifica X-Story-Title", payload.get("title") == "El Sapo Feliz", str(payload.get("title")))


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
        ok("quedó en check-in o esperando otro", engine.state in ("checking_in", "awaiting_more"), engine.state)


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
        lib.save_story("El sapo valiente", _long_story_text())
        engine = StoryEngine(lib)
        engine.process_or_passthrough(
            "cuento",
            {"intent_name": "story_request", "response": "", "confidence": 1.0},
        )
        first = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        ok("primer bloque pide seguimos", first.get("story_checkin") == "¿Seguimos?")
        ok("sigue en check-in", engine.state == "checking_in", engine.state)
        engine.advance_silence()
        ok("silencio avanza", engine.state in ("checking_in", "reflecting"), engine.state)
        stop = engine.process_or_passthrough("basta", {"intent_name": "unknown", "response": ""})
        ok("basta en check-in para", not engine.is_active)
        ok("cierre", "paramos" in stop["response"].lower() or "listo" in stop["response"].lower())


def test_engine_last_chunk_reflection() -> None:
    from story_engine import CLOSING_PROMPT

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
        ok("no pide reflexión al terminar", not last.get("story_need_reflection"), str(last.keys()))
        ok("termina esperando otro", engine.state == "awaiting_more", engine.state)
        ok(
            "cierra preguntando si otro",
            last.get("story_closing") == CLOSING_PROMPT,
            str(last.get("story_closing")),
        )
        otro = engine.process_or_passthrough("sí", {"intent_name": "unknown", "response": ""})
        ok("sí pide otro cuento", engine.state == "offering" or bool(otro.get("response")), str(engine.state))


def test_digest_limit() -> None:
    from story_engine import make_digest
    long = "palabra " * 200
    d = make_digest(long, 400)
    ok("digest respeta límite", len(d) <= 401)


def test_min_words_constant() -> None:
    ok("mínimo 80 palabras", MIN_WORDS == 80)


def test_drop_turn_while_story_speaks() -> None:
    from story_engine import should_drop_turn_while_story_speaks

    ok(
        "sí se descarta si el cuento está hablando",
        should_drop_turn_while_story_speaks(True, "Sí."),
    )
    ok(
        "cuento se descarta si el cuento está hablando",
        should_drop_turn_while_story_speaks(True, "Teo, ¿me contás un cuento?"),
    )
    ok(
        "basta no se descarta",
        not should_drop_turn_while_story_speaks(True, "basta"),
    )
    ok(
        "parar no se descarta",
        not should_drop_turn_while_story_speaks(True, "paramos"),
    )
    ok(
        "si no está hablando no se descarta el sí",
        not should_drop_turn_while_story_speaks(False, "Sí."),
    )


def test_workers_story_timer_espera_stt() -> None:
    src = Path(__file__).resolve().parent.joinpath("workers.py").read_text(
        encoding="utf-8"
    )
    ok("timer mira stt en vuelo", "_stt_in_flight" in src)
    ok("pipeline del cuento silencia el mic", "_story_pipeline_active" in src)
    ok("TTS extra pide permiso de cuento", "story=True" in src or "story = True" in src)
    speak_fn = src[src.find("def _speak_story_payload") : src.find("def _story_reflection_question")]
    ok(
        "no arma pregunta de reflexión al leer",
        "_story_reflection_question" not in speak_fn,
        "sigue llamando al LLM de reflexión",
    )


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
    test_ingest_title_override()
    test_ingest_title_empty_falls_back()
    test_ingest_title_truncated()
    test_update_story_title()
    test_update_story_text()
    test_update_story_keeps_id_and_created_at()
    test_update_story_rejects_invalid_text()
    test_update_story_missing_returns_none()
    test_http_get_story_and_404()
    test_http_put_story_and_404()
    test_http_upload_story_title_header()
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
    test_drop_turn_while_story_speaks()
    test_workers_story_timer_espera_stt()
    print(f"\nPASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)
