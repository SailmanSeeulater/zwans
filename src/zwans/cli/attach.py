"""`zwans attach`: follow and drive a session running in `zwans serve` from the terminal,
alongside the web UI or other terminals."""

import asyncio
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit, urlunsplit

import httpx
import typer
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from zwans.cli.render import Renderer
from zwans.events import PermissionRequested, PermissionResolved, TurnStarted, parse_event

ANSWERS = {"y": "once", "yes": "once", "a": "always", "always": "always"}


class AttachError(Exception):
    pass


def open_remote(
    url: str, token: str, session: str | None, workspace: Path, mode: str | None
) -> dict[str, Any]:
    """Open `session` in the server (resuming it if it isn't running), or start a new one in
    `workspace`. Returns its status."""
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, Any] = {"mode": mode} if mode else {}
    try:
        with httpx.Client(base_url=url, headers=headers, timeout=60) as client:
            if session is None:
                body["workspace"] = str(workspace.resolve())
                response = client.post("/api/sessions", json=body)
            else:
                response = client.post(f"/api/sessions/{session}/open", json=body or None)
    except httpx.TransportError as exc:
        raise AttachError(f"Can't reach the Zwans server at {url}: {exc}") from exc
    if response.status_code == 401:
        raise AttachError("The server refused the token. Is it the one `zwans serve` started?")
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise AttachError(str(detail))
    status: dict[str, Any] = response.json()
    return status


class Attached:
    """One terminal following one live session."""

    def __init__(self, url: str, token: str, session_id: str, stdin: TextIO | None = None) -> None:
        self.stdin = stdin or sys.stdin
        self.events_url = _websocket_url(url, f"/api/sessions/{session_id}/events")
        self.token = token
        self.renderer = Renderer()
        self.running = False
        self.waiting: list[str] = []  # permission questions this terminal could answer
        self.lines: asyncio.Queue[str | None] = asyncio.Queue()
        self.ws: ClientConnection | None = None
        self.done = asyncio.Event()
        self._sending: set[asyncio.Task[None]] = set()  # kept so they aren't collected early
        self._typed: list[str] = []  # prompts sent from this terminal, already on screen

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        _read_lines_in_background(loop, self.lines, self.stdin)
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGINT, self._ctrl_c)
        async with connect(self.events_url, max_size=None) as ws:
            self.ws = ws
            await ws.send(json.dumps({"type": "auth", "token": self.token}))
            reader = asyncio.create_task(self._read(ws))
            writer = asyncio.create_task(self._write(ws))
            stop = asyncio.create_task(self.done.wait())
            await asyncio.wait({reader, writer, stop}, return_when="FIRST_COMPLETED")
            for task in (reader, writer, stop):
                task.cancel()

    def _ctrl_c(self) -> None:
        """Ctrl+C stops the running turn; when nothing is running, it detaches."""
        if self.running and self.ws is not None:
            typer.secho("\nInterrupting the turn. Ctrl+C again when it stops detaches.", dim=True)
            task = asyncio.ensure_future(self.ws.send(json.dumps({"type": "interrupt"})))
            self._sending.add(task)
            task.add_done_callback(self._sending.discard)
        else:
            self.done.set()

    async def _read(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                self._show(json.loads(raw))
        except ConnectionClosed as closed:
            reason = closed.rcvd.reason if closed.rcvd else ""
            typer.secho(f"\nThe server closed the connection. {reason}".rstrip(), fg="yellow")

    def _show(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "backlog":
            for event in message.get("events", []):
                self._show(event)
            if not self.running:
                self._prompt()
            return
        if kind == "status":
            was_running = self.running
            self.running = bool(message.get("running"))
            self.waiting = [c for c in self.waiting if c in message.get("waiting_for", [])]
            if was_running and not self.running:
                self._prompt()
            return
        if kind == "server_error":
            typer.secho(f"  {message.get('message')}", fg="yellow")
            return
        try:
            event = parse_event(message)
        except ValidationError:
            return  # from a newer server; nothing to show
        if isinstance(event, TurnStarted):
            if event.prompt in self._typed:
                self._typed.remove(event.prompt)
            else:  # sent from the browser or another terminal, or before this one attached
                typer.secho(f"\n» {event.prompt}", bold=True)
        elif isinstance(event, PermissionRequested):
            self.waiting.append(event.call_id)
            always = ", ".join(event.rules) or "this call"
            typer.secho(f"  ? {event.reason}", fg="yellow")
            typer.secho(f"  Allow it? [y]es / [a]lways ({always}) / [N]o: ", fg="yellow", nl=False)
        elif isinstance(event, PermissionResolved) and event.call_id in self.waiting:
            self.waiting.remove(event.call_id)
            typer.echo("allowed" if event.allowed else "declined")
        self.renderer.on_event(event)

    def _prompt(self) -> None:
        typer.echo("\n> ", nl=False)

    async def _write(self, ws: ClientConnection) -> None:
        while True:
            line = await self.lines.get()
            if line is None:  # end of input
                return
            line = line.strip()
            if self.waiting:
                answer = ANSWERS.get(line.lower(), "no")
                call_id = self.waiting[0]
                await ws.send(json.dumps({"type": "approve", "call_id": call_id, "answer": answer}))
            elif line in ("exit", "quit"):
                return
            elif line:
                self._typed.append(line)
                await ws.send(json.dumps({"type": "prompt", "text": line}))
            elif not self.running:
                self._prompt()


def _read_lines_in_background(
    loop: asyncio.AbstractEventLoop, lines: asyncio.Queue[str | None], stream: TextIO
) -> None:
    """Read stdin on a daemon thread, which can't keep Zwans from exiting the way a blocked
    input() in the event loop's thread pool would."""

    def read() -> None:
        for line in stream:
            loop.call_soon_threadsafe(lines.put_nowait, line)
        loop.call_soon_threadsafe(lines.put_nowait, None)

    threading.Thread(target=read, daemon=True).start()


def _websocket_url(url: str, path: str) -> str:
    parts = urlsplit(url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, path, "", ""))
