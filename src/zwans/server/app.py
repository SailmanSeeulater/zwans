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
import base64
import binascii
import contextlib
import dataclasses
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from zwans import __version__, usage
from zwans import demo as zwans_demo
from zwans.config import ConfigError
from zwans.executor.docker import DockerError
from zwans.images import ImageError, image_block
from zwans.messages import ImageBlock
from zwans.policy.rules import Mode, PolicyError
from zwans.providers.catalog import canonical, list_all, register_prices, resolve
from zwans.room import AgentSpec, RoomError
from zwans.runtime import is_chat
from zwans.server import evals
from zwans.server.live import Busy, HubSettings, LiveSession, Message, RewindError, SessionHub
from zwans.server.rooms import MAX_TURNS, LiveRoom, RoomHub
from zwans.server.rooms import act as act_in_room
from zwans.store import SessionError, SessionStore

AUTH_TIMEOUT = 10.0  # seconds a WebSocket has to send the token
CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
MAX_PROMPT_IMAGES = 5  # per message; each is up to 3.75 MB, so about 25 MB of base64

NO_UI = """<!doctype html><meta charset="utf-8"><title>Zwans</title>
<p>The Zwans server is running, but the web UI isn't built. Build it with
<code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, then restart
<code>zwans serve</code>. If Zwans is installed with <code>uv tool install</code>, reinstall
it after the build: <code>uv tool install --reinstall .</code></p>"""


@dataclass
class ServerSettings(HubSettings):
    token: str = ""
    reports: Path = Path("evals/reports")
    web_dir: Path | None = None  # the built UI (web/out); None serves a note instead
    dev_origin: str | None = None  # a `next dev` server allowed to call the API


class NewSession(BaseModel):
    workspace: str = ""
    mode: Mode | None = None
    model: str | None = None
    demo: bool = False  # the scripted replay in a copy of the demo project; ignores the rest
    chat: bool = False  # a conversation with no folder and no tools; takes only the model


class ChooseModel(BaseModel):
    name: str


class MarkSession(BaseModel):
    name: str | None = None  # "" gives back the title from the first prompt
    pinned: bool | None = None


class RewindTo(BaseModel):
    turn: int  # the turn to undo, with every turn after it


class OpenSession(BaseModel):
    mode: Mode | None = None


class NewRoom(BaseModel):
    topic: str
    agents: list[AgentSpec]
    turns: int = Field(default=6, ge=0, le=MAX_TURNS)  # to run at once; 0 waits for the user
    budget: float | None = Field(default=None, ge=0)


def create_app(settings: ServerSettings) -> FastAPI:
    hub = SessionHub(settings)
    rooms = RoomHub(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await rooms.close_all()
        await hub.close_all()

    app = FastAPI(
        title="Zwans", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.hub = hub
    app.state.rooms = rooms
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
                    "title": info.label,
                    "named": bool(info.name),
                    "pinned": info.pinned,
                    "workspace": info.workspace,
                    "model": info.model,
                    "turns": info.turns,
                    "updated_at": info.updated_at,
                    "dollars": float(info.usage.get("dollars", 0.0)),
                    "live": info.id in hub.live,
                    "chat": is_chat(info.workspace, settings.config.home),
                }
                for info in saved
            ],
        }

    @api.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(body: NewSession) -> Message:
        try:
            if body.demo:
                live = await hub.demo(body.mode)
            elif body.chat:
                live = await hub.chat(body.model)
            elif not body.workspace:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a folder to work in.")
            else:
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

    @api.get("/sessions/{session_id}/request")
    def last_request(session_id: str) -> dict[str, Any]:
        """The body of the last request this session sent to the model, as the API got it.
        Null before the first call. It never holds the credential, which the client sends."""
        provider = _live(hub, session_id).opened.session.provider
        request = getattr(provider, "last_request", None)
        return {"request": json.loads(json.dumps(request, default=str)) if request else None}

    @api.post("/sessions/{session_id}/model")
    async def set_model(session_id: str, body: ChooseModel) -> Message:
        """Switch the session's model, for its next turns. Async so it runs on the event
        loop's thread: the session's SQLite connection only works on the thread that made it,
        and a plain `def` route runs in a worker thread."""
        live = _live(hub, session_id)
        try:
            live.set_model(body.name)
        except Busy as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return live.status()

    @api.get("/models")
    async def models(provider: str | None = None) -> dict[str, Any]:
        """The models each provider offers. Local servers are asked what they have; remote
        ones only when `provider` names them."""
        try:
            listings = await list_all(settings.config, settings.env, only=provider)
        except ConfigError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return {"providers": [dataclasses.asdict(listing) for listing in listings]}

    @api.get("/sessions/{session_id}/turns")
    async def undoable_turns(session_id: str) -> dict[str, Any]:
        """The turns that can be undone, newest first, each with the files it changed."""
        live = _live(hub, session_id)
        return {"turns": await live.undoable_turns(), "problem": live.undo_problem()}

    @api.post("/sessions/{session_id}/rewind")
    async def rewind(session_id: str, body: RewindTo) -> dict[str, Any]:
        """Undo a turn and every turn after it: the files go back to how they were before
        it, and the conversation ends just before it. Clients then reconnect to the session."""
        _live(hub, session_id)
        try:
            rewound = await hub.rewind(session_id, body.turn)
        except Busy as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except RewindError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except (SessionError, ConfigError, PolicyError, DockerError) as exc:
            # The files went back, but the session couldn't be reopened.
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
        return {
            "status": rewound.live.status(),
            "undone": [{"status": c.status, "path": c.path} for c in rewound.undone],
            "draft": rewound.draft,
        }

    @api.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def close_session(session_id: str) -> None:
        _live(hub, session_id)
        await hub.close(session_id)

    @api.delete("/sessions/{session_id}/saved", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_session(session_id: str) -> None:
        """Delete a session for good, open or not: the conversation, its transcript and the
        tool output kept for it. Files it changed stay as they are."""
        try:
            await hub.delete(session_id)
        except Busy as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except SessionError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @api.patch("/sessions/{session_id}/saved", status_code=status.HTTP_204_NO_CONTENT)
    async def mark_session(session_id: str, body: MarkSession) -> None:
        """Rename or pin a session, open or not. Async, for the open session it tells."""
        try:
            hub.mark(session_id, name=body.name, pinned=body.pinned)
        except SessionError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @api.get("/usage")
    def usage_over_time() -> dict[str, Any]:
        """Tokens and dollars by day, week, month and year, in this machine's timezone."""
        register_prices(settings.config)  # the config's, known before any session opens
        calls = usage.read_calls(settings.config.home)
        return usage.summarize(calls, datetime.now().astimezone())

    @api.get("/demo")
    def demo_prompts() -> dict[str, Any]:
        """What the home screen needs before anything is started: what the demo's turns
        are scripted for, the model a new session gets, and why that model can't be used yet
        if it can't."""
        problem = _credential_problem(settings)
        return {
            "prompts": list(zwans_demo.PROMPTS),
            "note": zwans_demo.NOTE,
            "has_credential": problem is None,  # whether one is set; it may still be refused
            "credential_problem": problem,
            "model": canonical(settings.config.model),  # what a new session starts with
        }

    @api.get("/evals")
    def list_runs() -> list[dict[str, Any]]:
        return evals.list_runs(settings.reports)

    @api.get("/evals/leaderboard")
    def leaderboard() -> list[dict[str, Any]]:
        return evals.leaderboard(settings.reports)

    @api.get("/evals/compare")
    def compare_runs(a: str, b: str) -> dict[str, Any]:
        try:
            return evals.compare_runs(settings.reports, a, b)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No report is named {exc}.") from exc

    @api.get("/evals/{name}")
    def get_run(name: str) -> dict[str, Any]:
        try:
            return evals.get_run(settings.reports, name)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No report is named {exc}.") from exc

    @api.get("/evals/{name}/transcripts/{file}")
    def get_transcript(name: str, file: str) -> list[dict[str, Any]]:
        try:
            return evals.get_transcript(settings.reports, name, file)
        except evals.ReportNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No transcript {exc}") from exc

    @api.get("/rooms")
    def list_rooms() -> dict[str, Any]:
        return {"saved": rooms.saved()}

    @api.post("/rooms", status_code=status.HTTP_201_CREATED)
    async def create_room(body: NewRoom) -> Message:
        """A room of agents, each on its own model, that starts talking about the topic."""
        try:
            live = await rooms.create(body.topic, body.agents, body.turns, body.budget)
        except RoomError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        return live.status()

    @api.post("/rooms/{room_id}/open")
    async def open_room(room_id: str) -> Message:
        try:
            live = await rooms.open(room_id)
        except RoomError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return live.status()

    @api.get("/rooms/{room_id}")
    def get_room(room_id: str) -> Message:
        return _live_room(rooms, room_id).status()

    @api.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def close_room(room_id: str) -> None:
        _live_room(rooms, room_id)
        await rooms.close(room_id)

    app.include_router(api)

    async def authorized(ws: WebSocket) -> bool:
        """Accept the socket if it comes from the UI's own page and its first message carries
        the token; close it otherwise."""
        if not _same_origin(ws, settings.dev_origin):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return False
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT)
        except (TimeoutError, WebSocketDisconnect, ValueError):
            first = None
        if not (isinstance(first, dict) and first.get("type") == "auth") or not valid(
            first.get("token")
        ):
            await ws.close(code=CLOSE_UNAUTHORIZED)
            return False
        return True

    @app.websocket("/api/rooms/{room_id}/events")
    async def room_events(ws: WebSocket, room_id: str) -> None:
        if not await authorized(ws):
            return
        live = rooms.live.get(room_id)
        if live is None:
            await ws.close(code=CLOSE_NOT_FOUND, reason="That room isn't open.")
            return
        queue = live.subscribe()
        try:
            await ws.send_json(live.status())
            async with anyio.create_task_group() as tasks:

                async def send() -> None:
                    try:
                        await _send(ws, queue)
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    finally:
                        tasks.cancel_scope.cancel()

                tasks.start_soon(send)
                await _listen_in_room(ws, live, queue)
                tasks.cancel_scope.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            live.unsubscribe(queue)

    @app.websocket("/api/sessions/{session_id}/events")
    async def session_events(ws: WebSocket, session_id: str) -> None:
        if not await authorized(ws):
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


def _credential_problem(settings: ServerSettings) -> str | None:
    """Why the configured model can't be used yet, or None when the key it needs is set."""
    try:
        resolve(settings.config.model, settings.config, settings.env)
    except ConfigError as exc:
        return str(exc)
    return None


def _live(hub: SessionHub, session_id: str) -> LiveSession:
    live = hub.live.get(session_id)
    if live is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That session isn't open.")
    return live


def _live_room(rooms: RoomHub, room_id: str) -> LiveRoom:
    live = rooms.live.get(room_id)
    if live is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That room isn't open.")
    return live


async def _listen_in_room(ws: WebSocket, live: LiveRoom, replies: asyncio.Queue[Message]) -> None:
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            try:
                message = await ws.receive_json()
            except ValueError:
                replies.put_nowait({"type": "server_error", "message": "That wasn't JSON."})
                continue
            problem = act_in_room(live, message if isinstance(message, dict) else {})
            if problem:
                replies.put_nowait({"type": "server_error", "message": problem})


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
        try:
            images = _images(message.get("images"))
        except ImageError as exc:
            return str(exc)
        if not text and not images:
            return "The prompt is empty."
        try:
            live.prompt(text or "What do you see in this image?", images)
        except Busy as exc:
            return str(exc)
    elif kind == "approve":
        if not live.answer(str(message.get("call_id", "")), str(message.get("answer", ""))):
            return "Nothing is waiting for that answer."
    elif kind == "answer":
        if not live.answer_question(str(message.get("text", ""))):
            return "No question is waiting for an answer."
    elif kind == "interrupt":
        live.interrupt()
    else:
        return f"Unknown message type: {kind!r}"
    return None


def _images(value: object) -> list[ImageBlock]:
    """The images sent with a prompt, as [{"name", "data"}] with base64 data, checked as
    the terminal checks an @image: by their bytes, not their names. Raises ImageError."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImageError("images must be a list.")
    if len(value) > MAX_PROMPT_IMAGES:
        raise ImageError(f"A message can carry at most {MAX_PROMPT_IMAGES} images.")
    blocks = []
    for number, item in enumerate(value, start=1):
        item = item if isinstance(item, dict) else {}
        name = str(item.get("name") or f"image {number}")
        try:
            data = base64.b64decode(str(item.get("data", "")), validate=True)
        except binascii.Error as exc:
            raise ImageError(f"{name} isn't base64.") from exc
        blocks.append(image_block(data, name))
    return blocks
