"""
J.A.R.V.I.S. v3 — Server
=========================
FastAPI + Socket.IO backend.

Socket.IO events  (browser → server):
    start_session   — start a JARVIS session, returns LiveKit token
    stop_session    — end the session
    audio_upload    — binary WebM audio blob → Whisper → process
    text_in         — text message → process directly

Socket.IO events  (server → browser):
    session_ready   — {livekit_url, livekit_token, room_name, fallback_audio}
    transcript      — {text}        Whisper transcript
    thinking        — {}            Gemini is processing
    response_text   — {text}        JARVIS spoken reply
    ui_event        — {type, ...}   open window / show results
    speaking        — {}            TTS started
    audio_out       — {data, format} base64 MP3 fallback if no LiveKit
    done            — {}            turn complete, ready for next input
    error           — {message}
    status          — {message}

HTTP endpoints:
    GET  /           — frontend
    GET  /api/status — health check
    GET  /api/world/live|summary|covid|all — world monitor (unchanged)
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
import socketio  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.jarvis_agent import JarvisAgent
from backend import livekit_room, data_store
from backend.llm import enabled_providers

# World monitor (optional — keep existing endpoints)
try:
    from backend.scrapers.worldometer import (
        fetch_world_population, fetch_world_covid, fetch_all_world_data,
    )
    from backend.cache import cache
    from backend.ai_summary import (
        summarize_world_population, summarize_covid_data, analyze_world_metrics,
    )
    _WORLD_MONITOR = True
except ImportError:
    def _fetch_unavailable(*_args: object, **_kwargs: object) -> dict:  # type: ignore[return]
        raise RuntimeError("World monitor dependencies are unavailable")

    async def _summarize_unavailable(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("World monitor dependencies are unavailable")

    class _NoopCache:
        @staticmethod
        def get(_key: object) -> None:
            return None

        @staticmethod
        def set(_key: object, _value: object) -> None:
            return None

    fetch_world_population = _fetch_unavailable
    fetch_world_covid = _fetch_unavailable
    fetch_all_world_data = _fetch_unavailable
    summarize_world_population = _summarize_unavailable
    summarize_covid_data = _summarize_unavailable
    analyze_world_metrics = _summarize_unavailable
    cache = _NoopCache()

    _WORLD_MONITOR = False

# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

# Force UTF-8 on stdout/stderr so the agent never crashes when an LLM reply
# contains characters Windows cp1252 can't encode (non-breaking hyphen, em
# dash, smart quotes, emoji, etc.). Logging handlers inherit the stream
# encoding, so this protects every logger.info / print downstream.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("jarvis.server")

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
CEREBRAS_KEY = os.getenv("CEREBRAS_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

ACTIVE_LLM_PROVIDERS = [p.name for p in enabled_providers()]

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

# ── FastAPI ───────────────────────────────────────────────────────────────────

app = FastAPI(title="J.A.R.V.I.S. v3", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/status")
async def api_status():
    return {
        "status": "online",
        "version": "4.0.0",
        "groq": bool(GROQ_KEY),
        "cerebras": bool(CEREBRAS_KEY),
        "openrouter": bool(OPENROUTER_KEY),
        "gemini": bool(GEMINI_KEY),
        "llm_providers": ACTIVE_LLM_PROVIDERS,
        "livekit": livekit_room.is_configured(),
        "world_monitor": _WORLD_MONITOR,
    }


# ── World monitor endpoints (preserved) ──────────────────────────────────────

if _WORLD_MONITOR:
    @app.get("/api/world/live")
    async def world_live():
        cached = cache.get("world_population")
        if cached:
            return {"source": "worldometer", "data": cached, "cached": True}
        data = fetch_world_population()
        cache.set("world_population", data)
        return {"source": "worldometer", "data": data, "cached": False}

    @app.get("/api/world/summary")
    async def world_summary():
        if not ACTIVE_LLM_PROVIDERS:
            return {"error": "No LLM provider configured (set GROQ_API_KEY)"}
        data = fetch_world_population()
        summary = await summarize_world_population(data)
        return {"data": data, "summary": summary, "source": ACTIVE_LLM_PROVIDERS[0]}

    @app.get("/api/world/covid")
    async def world_covid():
        cached = cache.get("world_covid")
        if cached:
            return cached
        covid_data = fetch_world_covid()
        summary = (
            await summarize_covid_data({"covid": covid_data})
            if ACTIVE_LLM_PROVIDERS else ""
        )
        result = {"data": covid_data, "summary": summary}
        cache.set("world_covid", result)
        return result

    @app.get("/api/world/all")
    async def world_all():
        all_data = fetch_all_world_data()
        analysis = await analyze_world_metrics(all_data) if ACTIVE_LLM_PROVIDERS else ""
        return {"metrics": all_data, "analysis": analysis}


if (FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


# ── Socket.IO ─────────────────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_timeout=30,
    ping_interval=10,
    max_http_buffer_size=25 * 1024 * 1024,  # 25 MB for audio blobs
)

# sid → JarvisAgent
_agents: dict[str, JarvisAgent] = {}
_tasks:  dict[str, asyncio.Task] = {}


def _room_name(sid: str) -> str:
    return f"jarvis-{sid[:8]}"


async def _forward(sid: str, kind: str, data):
    await sio.emit(kind, data, to=sid)


@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")
    await sio.emit("status", {"message": "Connected to J.A.R.V.I.S. command center."}, to=sid)


@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")
    await _teardown(sid)


async def _teardown(sid: str):
    agent = _agents.pop(sid, None)
    task = _tasks.pop(sid, None)
    if agent:
        try:
            await agent.stop()
        except Exception:
            pass
    if task:
        task.cancel()
    data_store.clear_session(sid)


@sio.event
async def start_session(sid, data=None):
    """Initialise a JARVIS session. Returns LiveKit token (or fallback flag)."""
    if not ACTIVE_LLM_PROVIDERS:
        await sio.emit("error", {
            "message": (
                "No LLM provider configured. Set at least one in .env: "
                "GROQ_API_KEY (free at console.groq.com/keys), CEREBRAS_API_KEY, "
                "OPENROUTER_API_KEY, or GEMINI_API_KEY."
            ),
        }, to=sid)
        return
    if not GROQ_KEY:
        await sio.emit("error", {
            "message": "GROQ_API_KEY not set in .env — required for speech-to-text (free at console.groq.com/keys)",
        }, to=sid)
        return

    if sid in _agents:
        await sio.emit("status", {"message": "Session already active."}, to=sid)
        return

    room = _room_name(sid)

    # Build LiveKit info for browser
    lk_token = None
    lk_url = None
    if livekit_room.is_configured():
        try:
            lk_token = livekit_room.make_user_token(room, sid)
            lk_url = livekit_room.LIVEKIT_URL
        except Exception as exc:
            logger.warning(f"LiveKit token error: {exc}")

    async def on_event(kind: str, payload):
        await _forward(sid, kind, payload)

    agent = JarvisAgent(room_name=room, on_event=on_event, sid=sid)
    _agents[sid] = agent
    _tasks[sid] = asyncio.create_task(agent.run())

    await sio.emit("session_ready", {
        "livekit_url": lk_url,
        "livekit_token": lk_token,
        "room_name": room,
        "fallback_audio": lk_token is None,   # browser must play audio_out events
    }, to=sid)
    logger.info(f"Session started for {sid} (room={room}, livekit={lk_token is not None})")


@sio.event
async def stop_session(sid, data=None):
    await _teardown(sid)
    await sio.emit("status", {"message": "Session ended."}, to=sid)


@sio.event
async def audio_upload(sid, data):
    """Receive a WebM audio blob from the browser after the user stops recording."""
    agent = _agents.get(sid)
    if not agent:
        await sio.emit("error", {"message": "No active session. Call start_session first."}, to=sid)
        return
    # data arrives as bytes via Socket.IO binary
    audio_bytes = bytes(data) if not isinstance(data, bytes) else data
    await agent.send_audio(audio_bytes)


@sio.event
async def text_in(sid, data):
    """Bypass STT — send text directly to JARVIS."""
    agent = _agents.get(sid)
    if not agent:
        await sio.emit("error", {"message": "No active session. Call start_session first."}, to=sid)
        return
    text = data if isinstance(data, str) else data.get("text", "")
    if text.strip():
        await agent.send_text(text)


@sio.event
async def file_upload(sid, data):
    """
    Receive a data file from the browser for analytics.
    data: {"filename": "sales.csv", "bytes": <binary>}  OR raw bytes with name in meta.
    """
    if not _agents.get(sid):
        await sio.emit("error", {"message": "No active session. Start a session first."}, to=sid)
        return

    try:
        if isinstance(data, dict):
            filename = data.get("filename", "upload.csv")
            raw = data.get("bytes") or data.get("data") or b""
            if isinstance(raw, list):
                raw = bytes(raw)
        else:
            filename = "upload.csv"
            raw = bytes(data) if not isinstance(data, bytes) else data

        if not raw:
            await sio.emit("error", {"message": "Empty file received."}, to=sid)
            return

        path = data_store.save_file(sid, filename, raw)
        files = data_store.list_files(sid)
        logger.info(f"File uploaded by {sid}: {filename} ({len(raw):,} bytes) → {path}")

        await sio.emit("file_ready", {
            "filename": filename,
            "size": len(raw),
            "files": files,
            "message": f"File '{filename}' uploaded. You can now ask JARVIS to analyze it.",
        }, to=sid)

    except Exception as exc:
        logger.error(f"file_upload error for {sid}: {exc}")
        await sio.emit("error", {"message": f"File upload failed: {exc}"}, to=sid)


# World Monitor real-time stream (preserved)
_world_streams: dict[str, bool] = {}


@sio.event
async def world_stream_start(sid, data=None):
    if not _WORLD_MONITOR:
        return
    _world_streams[sid] = True
    while _world_streams.get(sid, False):
        try:
            world_data = fetch_all_world_data()
            summary = (
                await summarize_world_population(world_data)
                if ACTIVE_LLM_PROVIDERS else ""
            )
            await sio.emit("world_update", {
                "data": world_data,
                "summary": summary,
                "timestamp": world_data.get("timestamp"),
            }, to=sid)
            await asyncio.sleep(30)
        except Exception as exc:
            await sio.emit("world_error", {"error": str(exc)}, to=sid)
            await asyncio.sleep(5)


@sio.event
async def world_stream_stop(sid, data=None):
    _world_streams[sid] = False


# ── Combined ASGI app ─────────────────────────────────────────────────────────

combined_app = socketio.ASGIApp(sio, other_asgi_app=app)


def _safe_print(line: str) -> None:
    """Print a line, falling back to ASCII if the console can't encode it.

    Stock Windows `cmd.exe` runs cp1252; without this, the box-drawing banner
    crashes the server before uvicorn ever starts.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        try:
            print(line.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def main():
    import uvicorn
    banner_lines = [
        "+============================================================+",
        "|   J.A.R.V.I.S. v4 - Stark Industries Command Center        |",
        "|   STT : Groq Whisper-large-v3                              |",
        "|   LLM : Groq -> Cerebras -> OpenRouter -> Gemini (failover)|",
        "|   TTS : Edge TTS (free)   Tools: FastMCP / SSE             |",
        "+============================================================+",
    ]
    for line in banner_lines:
        _safe_print(line)

    ok, miss = "[OK]", "[--]"
    _safe_print(f"  Groq API       : {ok if GROQ_KEY else '[MISSING] required for STT + primary LLM'}")
    _safe_print(f"  Cerebras API   : {ok if CEREBRAS_KEY else miss + ' optional fallback'}")
    _safe_print(f"  OpenRouter API : {ok if OPENROUTER_KEY else miss + ' optional fallback'}")
    _safe_print(f"  Gemini API     : {ok if GEMINI_KEY else miss + ' optional fallback'}")
    _safe_print(f"  Active LLMs    : {', '.join(ACTIVE_LLM_PROVIDERS) or '[NONE] set at least one key'}")
    livekit_status = livekit_room.LIVEKIT_URL if livekit_room.is_configured() else "fallback audio mode"
    _safe_print(f"  LiveKit        : {livekit_status}")
    _safe_print(f"  Browser        : http://{HOST}:{PORT}")
    _safe_print("")

    uvicorn.run(
        "backend.server:combined_app",
        host=HOST,
        port=PORT,
        log_level="warning",
        reload=False,
    )


if __name__ == "__main__":
    main()
