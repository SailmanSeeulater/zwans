"""Sessions running in the server, and everyone watching them.

A live session keeps every event it has emitted, so a client that connects late, such as a
second browser tab or `zwans attach`, starts from the whole conversation and then follows
along. Any client can send the next prompt, answer a permission question, or interrupt the
turn; they all see the result, because it arrives as events.
"""

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zwans.config import Config
from zwans.events import Error, Event
from zwans.policy.engine import Approval, PermissionRequest
from zwans.runtime import OpenedSession, ProviderFactory, open_session
from zwans.store import SessionStore

log = logging.getLogger(__name__)

type Message = dict[str, Any]

ANSWERS = {"once": Approval.ONCE, "always": Approval.ALWAYS, "no": Approval.NO}


class Busy(Exception):
    """The session is already running a turn."""


class LiveSession:
    def __init__(self, opened: OpenedSession, warnings: list[str]) -> None:
        self.opened = opened
        self.warnings = warnings  # MCP servers that didn't start, an untrusted policy, ...
        self.events: list[Message] = _earlier_events(opened.transcript.path)
        self.clients: set[asyncio.Queue[Message]] = set()
        self.turn: asyncio.Task[None] | None = None
        self.pending: dict[str, asyncio.Future[Approval]] = {}
        opened.session.listeners.append(self._on_event)
        if opened.session.permissions is not None:
            opened.session.permissions.approver = self.approve

    @property
    def id(self) -> str:
        return self.opened.id

    @property
    def running(self) -> bool:
        return self.turn is not None and not self.turn.done()

    def status(self) -> Message:
        info, opened = self.opened.info, self.opened
        return {
            "type": "status",
            "id": info.id,
            "title": info.title or self._first_prompt(),
            "workspace": info.workspace,
            "model": opened.model,
            "mode": opened.policy.policy.mode,
            "executor": opened.config.executor,
            "running": self.running,
            "turns": opened.session.turn,
            "dollars": opened.meter.session_dollars,
            "context_tokens": opened.session.context_tokens(),
            "waiting_for": sorted(self.pending),  # permission questions nobody has answered
            "warnings": self.warnings,
        }

    def _first_prompt(self) -> str:
        for event in self.events:
            if event.get("type") == "turn_started":
                return str(event.get("prompt", ""))[:80]
        return ""

    def subscribe(self) -> tuple[list[Message], asyncio.Queue[Message]]:
        """Everything so far, and a queue for what comes next. Nothing happens between the
        two (there's no await), so no event is missed or seen twice."""
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self.clients.add(queue)
        return list(self.events), queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self.clients.discard(queue)

    def prompt(self, text: str) -> None:
        if self.running:
            raise Busy("A turn is already running. Wait for it, or interrupt it.")
        self.turn = asyncio.create_task(self._run(text))
        self._broadcast(self.status())

    def interrupt(self) -> None:
        if self.turn is not None:
            self.turn.cancel()

    def answer(self, call_id: str, answer: str) -> bool:
        future = self.pending.get(call_id)
        if future is None or future.done() or answer not in ANSWERS:
            return False
        future.set_result(ANSWERS[answer])
        return True

    async def approve(self, request: PermissionRequest) -> Approval:
        """The session's approver: waits until a client answers. The question itself went
        out as a PermissionRequested event just before this is called."""
        future: asyncio.Future[Approval] = asyncio.get_running_loop().create_future()
        self.pending[request.call_id] = future
        self._broadcast(self.status())
        try:
            return await future
        finally:
            self.pending.pop(request.call_id, None)

    async def close(self) -> None:
        self.interrupt()
        if self.turn is not None:
            await asyncio.gather(self.turn, return_exceptions=True)
        await self.opened.close()

    async def _run(self, text: str) -> None:
        try:
            await self.opened.session.send(text)
        except asyncio.CancelledError:
            pass  # interrupted; the session has already said so
        except Exception as exc:  # a bug, not a model error: those arrive as events
            log.exception("turn failed in session %s", self.id)
            self._on_event(Error(message=f"Zwans failed: {exc}"))
        finally:
            self.turn = None
            self._broadcast(self.status())

    def _on_event(self, event: Event) -> None:
        time = datetime.now(UTC).isoformat(timespec="milliseconds")
        message = {"time": time, **event.model_dump(mode="json")}
        self.events.append(message)
        self._broadcast(message)

    def _broadcast(self, message: Message) -> None:
        for queue in list(self.clients):
            queue.put_nowait(message)


@dataclass
class HubSettings:
    config: Config
    env: Mapping[str, str]
    make_provider: ProviderFactory | None = None  # tests replace the model


class SessionHub:
    """The server's live sessions, by id."""

    def __init__(self, settings: HubSettings) -> None:
        self.settings = settings
        self.live: dict[str, LiveSession] = {}
        self._opening = asyncio.Lock()  # so two clients resuming at once get one session

    async def create(
        self, workspace: Path, mode: str | None = None, model: str | None = None
    ) -> LiveSession:
        if not workspace.is_dir():
            raise FileNotFoundError(f"{workspace} isn't a folder")
        return await self._open(workspace=workspace, mode=mode, model=model)

    async def resume(self, id_or_prefix: str, mode: str | None = None) -> LiveSession:
        async with self._opening:
            session_id = self.saved_id(id_or_prefix)
            if session_id in self.live:
                return self.live[session_id]
            return await self._open(workspace=Path("."), resume=session_id, mode=mode)

    def saved_id(self, id_or_prefix: str) -> str:
        """Raises SessionError if no saved session matches."""
        store = SessionStore(self.settings.config.home / "sessions.db")
        try:
            return store.get(id_or_prefix).id
        finally:
            store.close()

    async def _open(self, **kwargs: Any) -> LiveSession:
        opened = open_session(
            self.settings.config,
            self.settings.env,
            make_provider=self.settings.make_provider,
            **kwargs,
        )
        try:
            _, problems = await opened.start()
        except BaseException:
            await opened.close()
            raise
        warnings = [f"MCP server skipped: {problem}" for problem in problems]
        if opened.policy.untrusted is not None:
            warnings.append(
                f"{opened.policy.untrusted} would loosen the policy or run hooks, but it isn't "
                "trusted, so those parts are left out. Trust it from the terminal with `zwans`."
            )
        live = LiveSession(opened, warnings)
        self.live[live.id] = live
        return live

    async def close(self, session_id: str) -> None:
        live = self.live.pop(session_id, None)
        if live is not None:
            await live.close()

    async def close_all(self) -> None:
        for session_id in list(self.live):
            await self.close(session_id)


def _earlier_events(path: Path) -> list[Message]:
    """What a resumed session did before, from its transcript."""
    events: list[Message] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # a line cut short when Zwans was killed
        if isinstance(record, dict):
            events.append(record)
    return events
