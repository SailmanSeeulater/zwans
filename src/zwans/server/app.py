"""The server's HTTP and WebSocket API, and the web UI's files.

Every /api route except /api/health needs the server's token, as `Authorization: Bearer
<token>`. A WebSocket sends it as its first message, {"type": "auth", "token": "..."},
because browsers can't set headers on one and a token in the URL would end up in logs.

/api/sessions/{id}/events is a session's WebSocket. After the token, the server sends the
session's status, then {"type": "backlog", "events": [...]} with everything so far, then
each new event as it happens, plus a fresh status whenever the session starts or stops
running or waits for an answer. A client may send:

    {"type": "prompt", "text": "..."}
    {"type": "approve", "call_id": "...", "answer": "once" | "always" | "no"}
    {"type": "interrupt"}

A request the session can't take gets {"type": "server_error", "message": "..."} back, to
that client only.
"""

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from zwans import __version__
from zwans.config import ConfigError
from zwans.executor.docker import DockerError
from zwans.policy.rules import Mode, PolicyError
from zwans.server import evals
from zwans.server.live import Busy, HubSettings, LiveSession, Message, SessionHub
from zwans.store import SessionError, SessionStore

AUTH_TIMEOUT = 10.0  # seconds a WebSocket has to send the token
CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404

NO_UI = """<!doctype html><meta charset="utf-8"><title>Zwans</title>
<p>The Zwans server is running, but the web UI isn't built. Build it with
<code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, then restart
<code>zwans serve</code>.</p>"""


@dataclass
class ServerSettings(HubSettings):
    token: str = ""
    reports: Path = Path("evals/reports")
    web_dir: Path | None = None  # the built UI (web/out); None serves a note instead
    dev_origin: str | None = None  # a `next dev` server allowed to call the API


class NewSession(BaseModel):
    workspace: str
    mode: Mode | None = None
    model: str | None = None


class OpenSession(BaseModel):
    mode: Mode | None = None


def create_app(settings: ServerSettings) -> FastAPI:
    hub = SessionHub(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await hub.close_all()

    app = FastAPI(
        title="Zwans", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.hub = hub
    if settings.dev_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.dev_origin],
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def valid(token: str | None) -> bool:
        return token is not None and secrets.compare_digest(token, settings.token)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not valid(token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong token.")

    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @api.get("/sessions")
    def list_sessions() -> dict[str, Any]:
        store = SessionStore(settings.config.home / "sessions.db")
        try:
            saved = store.recent(100)
        finally:
            store.close()
        return {
            "live": [live.status() for live in hub.live.values()],
            "saved": [
                {
                    "id": info.id,
                    "title": info.title,
                    "workspace": info.workspace,
                    "model": info.model,
                    "turns": info.turns,
                    "updated_at": info.updated_at,
                    "dollars": float(info.usage.get("dollars", 0.0)),
                    "live": info.id in hub.live,
                }
                for info in saved
            ],
        }

    @api.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(body: NewSession) -> Message:
        try:
            live = await hub.create(Path(body.workspace).expanduser(), body.mode, body.model)
        except (FileNotFoundError, ConfigError, PolicyError, DockerError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return live.status()

    @api.post("/sessions/{session_id}/open")
    async def open_session(session_id: str, body: OpenSession | None = None) -> Message:
        try:
            live = await hub.resume(session_id, body.mode if body else None)
        except SessionError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except (ConfigError, PolicyError, DockerError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return live.status()

    @api.get("/sessions/{session_id}")
    def get_session(session_id: str) -> Message:
        return _live(hub, session_id).status()

    @api.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def close_session(session_id: str) -> None:
        _live(hub, session_id)
        await hub.close(session_id)

    @api.get("/evals")
    def list_runs() -> list[dict[str, Any]]:
        return evals.list_runs(settings.reports)

    @api.get("/evals/compare")
    def compare_runs(a: str, b: str) -> dict[str, Any]:
        try:
            return evals.compare_runs(settings.reports, a, b)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No report {exc}") from exc

    @api.get("/evals/{name}")
    def get_run(name: str) -> dict[str, Any]:
        try:
            return evals.get_run(settings.reports, name)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No report {exc}") from exc

    @api.get("/evals/{name}/transcripts/{file}")
    def get_transcript(name: str, file: str) -> list[dict[str, Any]]:
        try:
            return evals.get_transcript(settings.reports, name, file)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No transcript {exc}") from exc

    app.include_router(api)

    @app.websocket("/api/sessions/{session_id}/events")
    async def session_events(ws: WebSocket, session_id: str) -> None:
        if not _same_origin(ws, settings.dev_origin):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT)
        except (TimeoutError, WebSocketDisconnect, ValueError):
            first = None
        if not (isinstance(first, dict) and first.get("type") == "auth") or not valid(
            first.get("token")
        ):
            await ws.close(code=CLOSE_UNAUTHORIZED)
            return
        live = hub.live.get(session_id)
        if live is None:
            await ws.close(code=CLOSE_NOT_FOUND, reason="That session isn't open.")
            return
        backlog, queue = live.subscribe()
        try:
            await ws.send_json(live.status())
            await ws.send_json({"type": "backlog", "events": backlog})
            async with anyio.create_task_group() as tasks:

                async def send() -> None:
                    try:
                        await _send(ws, queue)
                    except (WebSocketDisconnect, RuntimeError):
                        pass  # the client went away mid-send
                    finally:
                        tasks.cancel_scope.cancel()

                tasks.start_soon(send)
                await _listen(ws, live, queue)
                tasks.cancel_scope.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            live.unsubscribe(queue)

    if settings.web_dir is not None and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def no_ui() -> str:
            return NO_UI

    return app


def _live(hub: SessionHub, session_id: str) -> LiveSession:
    live = hub.live.get(session_id)
    if live is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session isn't open.")
    return live


def _same_origin(ws: WebSocket, dev_origin: str | None) -> bool:
    """A page on another site can open a WebSocket to localhost; it still needs the token,
    but there's no reason to let it try. Clients that aren't browsers send no Origin."""
    origin = ws.headers.get("origin")
    if origin is None or origin == dev_origin:
        return True
    return urlsplit(origin).netloc == ws.headers.get("host")


async def _send(ws: WebSocket, queue: asyncio.Queue[Message]) -> None:
    while True:
        await ws.send_json(await queue.get())


async def _listen(ws: WebSocket, live: LiveSession, replies: asyncio.Queue[Message]) -> None:
    """Act on what the client sends. Replies go through its queue, so only one task ever
    writes to the socket."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            try:
                message = await ws.receive_json()
            except ValueError:
                replies.put_nowait({"type": "server_error", "message": "That wasn't JSON."})
                continue
            problem = _act(live, message if isinstance(message, dict) else {})
            if problem:
                replies.put_nowait({"type": "server_error", "message": problem})


def _act(live: LiveSession, message: dict[str, Any]) -> str | None:
    """Do what a client asked. Returns why not, when it can't."""
    kind = message.get("type")
    if kind == "prompt":
        text = str(message.get("text", "")).strip()
        if not text:
            return "The prompt is empty."
        try:
            live.prompt(text)
        except Busy as exc:
            return str(exc)
    elif kind == "approve":
        if not live.answer(str(message.get("call_id", "")), str(message.get("answer", ""))):
            return "Nothing is waiting for that answer."
    elif kind == "interrupt":
        live.interrupt()
    else:
        return f"Unknown message type: {kind!r}"
    return None
