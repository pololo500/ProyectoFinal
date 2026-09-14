"""Servidor FastAPI: Whisper GPU + Llama 8B para la Pi."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from config import HOST, PORT, load_or_create_token
from handlers import handle_chat, handle_health, handle_speech, handle_transcribe
from llm_engine import LlmEngine
from stt_engine import SttEngine
from tts_engine import TtsEngine

stt_engine = SttEngine()
llm_engine = LlmEngine()
tts_engine = TtsEngine()
TOKEN = load_or_create_token()


def _auth_header(request: Any) -> str | None:
    return request.headers.get("authorization") or request.headers.get("Authorization")


def _console(msg: str) -> None:
    print(msg, flush=True)


def _peer(request: Any) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return str(host or "?")


def create_app() -> Any:
    app = FastAPI(title="TEO ServidorDePC")

    @app.get("/health")
    async def health(request: Request) -> Response:
        status, body = handle_health(
            stt_engine, llm_engine, TOKEN, _auth_header(request), tts_engine
        )
        return JSONResponse(body, status_code=status)

    @app.post("/v1/audio/transcriptions")
    async def transcribe(request: Request) -> Response:
        wav = await request.body()
        language = request.query_params.get("language") or "es"
        status, body = handle_transcribe(
            stt_engine,
            llm_engine,
            TOKEN,
            _auth_header(request),
            wav,
            request.headers.get("content-type"),
            language,
            log_fn=_console,
            peer=_peer(request),
        )
        return JSONResponse(body, status_code=status)

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        raw = await request.body()
        status, body = handle_chat(
            stt_engine,
            llm_engine,
            TOKEN,
            _auth_header(request),
            raw,
            log_fn=_console,
            peer=_peer(request),
        )
        return JSONResponse(body, status_code=status)

    @app.post("/v1/audio/speech")
    async def speech(request: Request) -> Response:
        raw = await request.body()
        status, payload, media = handle_speech(
            tts_engine,
            TOKEN,
            _auth_header(request),
            raw,
            log_fn=_console,
            peer=_peer(request),
        )
        if media == "audio/wav" and isinstance(payload, (bytes, bytearray)):
            return Response(content=bytes(payload), media_type="audio/wav", status_code=status)
        return JSONResponse(payload, status_code=status)

    return app


app = create_app()


def main() -> None:
    print("=== TEO ServidorDePC ===", flush=True)
    print(f"Bind {HOST}:{PORT}", flush=True)
    print(f"Token: {TOKEN_PATH_HINT()}", flush=True)
    print("Cargando modelos (puede tardar)...", flush=True)
    stt_engine.load()
    llm_engine.load()
    tts_engine.load()
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


def TOKEN_PATH_HINT() -> str:
    from config import TOKEN_PATH

    return f"{TOKEN[:8]}… ({TOKEN_PATH.name})"


if __name__ == "__main__":
    main()
