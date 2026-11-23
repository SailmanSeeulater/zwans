"""Sessions running in the server, and everyone watching them.

A live session keeps every event it has emitted, so a client that connects late, such as a
second browser tab or `zwans attach`, starts from the whole conversation and then follows
along. Any client can send the next prompt, answer a permission question, or interrupt the
turn; they all see the result, because it arrives as events.
"""

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zwans import demo as zwans_demo
from zwans import pricing, races, usage
from zwans.budget import parse_dollars
from zwans.checkpoints import Change, CheckpointError
from zwans.config import Config, ConfigError
from zwans.events import Error, Event, TurnEnded
from zwans.looping import parse_loop, run_loop
from zwans.messages import ImageBlock, TextBlock
from zwans.policy.engine import Approval, PermissionRequest
from zwans.providers.catalog import canonical
from zwans.providers.router import ModelRouter, helper
from zwans.runtime import OpenedSession, ProviderFactory, is_chat, open_session
from zwans.store import SessionError, SessionStore, title_of
from zwans.titles import title_model, write_title

log = logging.getLogger(__name__)

type Message = dict[str, Any]

ANSWERS = {"once": Approval.ONCE, "always": Approval.ALWAYS, "no": Approval.NO}


DIFF_CHARS = 400_000  # what the Changes panel is sent of a session's diff


class Busy(Exception):
    """The session is already running a turn."""


class RewindError(Exception):
    """Going back to before a turn isn't possible; the message says why."""


@dataclass(frozen=True)
class Rewound:
    live: "LiveSession"  # the session reopened before the turn
    undone: list[Change]  # what putting the files back changed
    draft: str  # the undone turn's prompt, to edit and send again


class LiveSession:
    def __init__(self, opened: OpenedSession, warnings: list[str], demo: bool = False) -> None:
        self.opened = opened
        self.warnings = warnings  # MCP servers that didn't start, an untrusted policy, ...
        self.demo = demo  # the scripted replay, with no API calls
        self.events: list[Message] = _earlier_events(opened.transcript.path)
        self.clients: set[asyncio.Queue[Message]] = set()
        self.turn: asyncio.Task[None] | None = None
        self.pending: dict[str, asyncio.Future[Approval]] = {}
        # The model's question to the person, while it waits for an answer; one at a time.
        self.question: asyncio.Future[str] | None = None
        self._one_question = asyncio.Lock()
        self._titling: asyncio.Task[None] | None = None  # writing its title, after turn one
        self._closing = False  # set by close(), so a steer left unread starts nothing
        opened.session.listeners.append(self._on_event)
        if opened.session.permissions is not None:
            opened.session.permissions.approver = self.approve
        opened.session.ctx = replace(opened.session.ctx, ask=self.ask)

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
            "title": info.label or self._first_prompt(),
            "pinned": info.pinned,
            "workspace": info.workspace,
            "model": opened.model,
            "mode": opened.policy.policy.mode,
            "executor": opened.config.executor,
            "running": self.running,
            "budget": opened.budget.dollars if opened.budget else None,  # the cap, in $
            "queued": list(opened.session.steering),  # sent mid-turn, not yet read
            "turns": opened.session.turn,
            "dollars": opened.meter.session_dollars,
            "context_tokens": opened.session.context_tokens(),
            # What nobody has answered yet: permission questions, by call, and the model's
            # own question.
            "waiting_for": [*sorted(self.pending), *(["question"] if self.question else [])],
            "warnings": self.warnings,
            "demo": self.demo,
            "chat": opened.chat,  # no project and no tools: only a conversation
            "local": self._local(),  # the model runs on this machine, for free
            # Who a stuck local session can hand its task to, when anyone.
            "handoff_model": opened.config.handoff_model if self._local() else None,
            "compact_at": opened.session.compact_at(opened.config.compact_at),
        }

    def _local(self) -> bool:
        return self.opened.model.partition("/")[0] in pricing.FREE_PROVIDERS

    def _first_prompt(self) -> str:
        for event in self.events:
            if event.get("type") == "turn_started":
                return title_of(str(event.get("prompt", "")))
        return ""

    def subscribe(self) -> tuple[list[Message], asyncio.Queue[Message]]:
        """Everything so far, and a queue for what comes next. Nothing happens between the
        two (there's no await), so no event is missed or seen twice."""
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self.clients.add(queue)
        return list(self.events), queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self.clients.discard(queue)

    def prompt(self, text: str, images: list[ImageBlock] | None = None) -> None:
        """Start a turn, or, while one runs, steer it: the text goes to the model at its next
        step. Anything still unread when the turn ends starts the next one."""
        if self.running:
            if images:
                raise Busy("Images can't be added to a running turn. Wait for it to finish.")
            self.opened.session.steering.append(text)
            self._broadcast(self.status())
            return
        self.turn = asyncio.create_task(self._run(text, images or []))
        self._broadcast(self.status())

    def set_model(self, name: str) -> None:
        """Switch the model for the next turns. Raises Busy, or ConfigError when the model
        can't be used (no such provider, or no key for it)."""
        if self.running:
            raise Busy("Wait for the turn to end before switching models.")
        router = self.opened.session.provider
        if not isinstance(router, ModelRouter):
            raise ConfigError("This session's model can't be switched.")
        router.set_model(canonical(name))
        self.opened.model = router.model
        self.opened.store.set_model(self.opened.id, router.model)
        self._broadcast(self.status())

    async def undoable_turns(self) -> list[dict[str, Any]]:
        """The turns that can be gone back to, newest first, each with what it changed."""
        checkpoints, session = self.opened.checkpoints, self.opened.session
        if self.demo or checkpoints is None or not checkpoints.available:
            return []
        earliest = session.earliest_turn()
        turns = []
        for turn in sorted(await checkpoints.turns(), reverse=True):
            if turn > session.turn or 0 < turn - 1 < earliest:
                continue
            changes = await checkpoints.changes(turn)
            turns.append(
                {
                    "turn": turn,
                    "prompt": session.prompt_of(turn),
                    "changes": [{"status": c.status, "path": c.path} for c in changes],
                }
            )
        return turns

    async def changes(self) -> dict[str, Any]:
        """Every file the session has changed so far, from its first checkpoint to now, with
        a unified diff of them; Bash's edits included. The diff is cut at DIFF_CHARS."""
        checkpoints = self.opened.checkpoints
        if self.demo or self.opened.chat or checkpoints is None or not checkpoints.available:
            return {"changes": [], "diff": "", "cut": False, "problem": self.undo_problem()}
        changes, diff = await checkpoints.since_start()
        cut = len(diff) > DIFF_CHARS
        return {
            "changes": [{"status": c.status, "path": c.path} for c in changes],
            "diff": diff[:DIFF_CHARS] if cut else diff,
            "cut": cut,
            "problem": None,
        }

    def undo_problem(self) -> str | None:
        """Why turns can't be undone in this session at all, if they can't."""
        checkpoints = self.opened.checkpoints
        if self.demo:
            return "The demo's turns can't be undone; start it again instead."
        if self.opened.chat:
            return "A chat has no files to put back, so its turns can't be undone."
        if checkpoints is None:
            return "Checkpoints are off (checkpoints = false), so turns can't be undone."
        return checkpoints.problem

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

    async def ask(self, question: str, options: Sequence[str]) -> str | None:
        """The session's asker, for the AskUser tool: waits until a client answers. The
        question itself reaches clients as that tool's call, which is how they show it."""
        async with self._one_question:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self.question = future
            self._broadcast(self.status())
            try:
                return await future
            finally:
                self.question = None

    def answer_question(self, text: str) -> bool:
        if self.question is None or self.question.done() or not text.strip():
            return False
        self.question.set_result(text.strip())
        return True

    async def close(self) -> None:
        self._closing = True
        if self._titling is not None:
            self._titling.cancel()
            await asyncio.gather(self._titling, return_exceptions=True)
        self.interrupt()
        if self.turn is not None:
            await asyncio.gather(self.turn, return_exceptions=True)
        await self.opened.close()

    def loop(self, argument: str) -> None:
        """Start /loop: work until a check passes. Raises Busy, or ValueError for an
        argument that can't be read."""
        if self.running:
            raise Busy("Wait for the turn to end, or stop it, before starting a loop.")
        if self.opened.chat or self.demo:
            raise Busy("A loop needs a project to run its check in.")
        spec = parse_loop(argument)
        work = run_loop(self.opened.session, self.opened.executor, spec)
        self.turn = asyncio.create_task(self._run_work(work))
        self._broadcast(self.status())

    def set_budget(self, text: str) -> None:
        """Set the spending cap: "2", "$0.50", or "off". Raises ValueError."""
        if self.opened.budget is None:
            raise ValueError("This session has no budget to set.")
        self.opened.budget.dollars = parse_dollars(text)
        self._broadcast(self.status())

    async def _run(self, text: str, images: list[ImageBlock]) -> None:
        await self._run_work(self.opened.session.send(text, images))

    async def _run_work(self, work: Coroutine[Any, Any, object]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            pass  # interrupted; the session has already said so
        except Exception as exc:  # a bug, not a model error: those arrive as events
            log.exception("turn failed in session %s", self.id)
            self._on_event(Error(message=f"Zwans failed: {exc}"))
        finally:
            self.turn = None
            unread = self.opened.session.steering
            if unread and not self._closing:
                # The turn ended before reading them (it errored or was stopped), so they
                # start the next one, as if sent just after it.
                self.opened.session.steering = []
                self.prompt("\n\n".join(unread))
            else:
                self._broadcast(self.status())

    def _on_event(self, event: Event) -> None:
        time = datetime.now(UTC).isoformat(timespec="milliseconds")
        message = {"time": time, **event.model_dump(mode="json")}
        self.events.append(message)
        self._broadcast(message)
        if isinstance(event, TurnEnded) and self._wants_title(event):
            self._titling = asyncio.get_running_loop().create_task(self._write_title())

    def _wants_title(self, event: TurnEnded) -> bool:
        """After the first turn of a real session that finished, once, unless the person has
        named it. A scripted model would spend its script on it, so only a routed one."""
        opened = self.opened
        return (
            opened.config.titles
            and not self.demo
            and self._titling is None
            and opened.session.turn == 1
            and event.stop_reason == "end_turn"
            and not opened.info.name
            and isinstance(opened.session.provider, ModelRouter)
        )

    async def _write_title(self) -> None:
        opened = self.opened
        session = opened.session
        reply = ""
        for message in reversed(session.messages):
            if message.role == "assistant":
                reply = "".join(b.text for b in message.content if isinstance(b, TextBlock))
                if reply:
                    break
        try:
            model = title_model(opened.config.title_model, opened.model)
            provider = helper(session.provider, model)
            title, response = await write_title(provider, session.prompt_of(1), reply)
        except asyncio.CancelledError:
            raise
        except Exception:  # a title is a nicety: the first prompt stays the title
            log.warning("couldn't write a title for session %s", self.id, exc_info=True)
            return
        if title and not opened.info.name and opened.recorder is not None:
            opened.recorder.title = title  # the recorder writes it with every update
            opened.info.title = title
            opened.store.set_title(self.id, title)
        if response is not None:
            session.emit(response.usage_event().model_copy(update={"purpose": "title"}))
        self._broadcast(self.status())

    def _broadcast(self, message: Message) -> None:
        for queue in list(self.clients):
            queue.put_nowait(message)


def share_budget(budget: float, lanes: list[LiveSession]) -> None:
    """Cap what a race's sessions spend between them, on top of each one's own cap: once
    their costs add up to `budget`, neither makes another model call."""

    def cap(own: Callable[[], str | None] | None) -> Callable[[], str | None]:
        def limit() -> str | None:
            spent = sum(lane.opened.meter.session_dollars for lane in lanes)
            if spent >= budget:
                return f"${spent:.2f} of the race's ${budget:.2f} budget spent"
            return own() if own is not None else None

        return limit

    for lane in lanes:
        lane.opened.session.limit = cap(lane.opened.session.limit)


@dataclass
class HubSettings:
    config: Config
    env: Mapping[str, str]
    make_provider: ProviderFactory | None = None  # tests replace the model
    demo_pace: float = zwans_demo.PACE  # tests replay the demo at full speed


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

    async def race(
        self,
        workspace: Path,
        prompt: str,
        models: Sequence[str],
        mode: str | None = None,
        budget: float | None = None,
    ) -> races.Race:
        """Give `prompt` to each of `models` at once, each in its own copy of `workspace`,
        with `budget` dollars between them when it's set. Raises FileNotFoundError,
        RaceError, or ConfigError for a model that can't be used."""
        if budget is not None and not budget > 0:
            raise races.RaceError("A race's budget is more than $0, or none.")
        if not workspace.is_dir():
            raise FileNotFoundError(f"{workspace} isn't a folder")
        if len(models) != len(races.LANES):
            raise races.RaceError(f"A race takes {len(races.LANES)} models.")
        if not prompt.strip():
            raise races.RaceError("Give the models a task.")
        home = self.settings.config.home
        race = races.Race(
            id=races.new_id(),
            prompt=prompt.strip(),
            workspace=str(workspace.resolve()),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            budget=budget,
        )
        folder = home / races.RACES / race.id
        opened: list[LiveSession] = []
        try:
            for letter, model in zip(races.LANES, models, strict=True):
                copy = folder / letter
                await asyncio.to_thread(races.copy_project, workspace, copy)
                live = await self.create(copy, mode=mode, model=model)
                opened.append(live)
                race.lanes.append(
                    races.Lane(model=live.opened.model, folder=str(copy), session_id=live.id)
                )
        except BaseException:
            for live in opened:
                await self.close(live.id)
            shutil.rmtree(folder, ignore_errors=True)
            raise
        races.save(home, race)
        if budget is not None:
            share_budget(budget, opened)
        for live in opened:
            live.prompt(race.prompt)
        return race

    def race_status(self, race: races.Race) -> dict[str, Any]:
        """A race as saved, with where each of its sessions stands and what they've cost."""
        lanes: list[dict[str, Any]] = []
        store = SessionStore(self.settings.config.home / "sessions.db")
        try:
            for lane in race.lanes:
                live = self.live.get(lane.session_id)
                if live is not None:
                    status = live.status()
                    lanes.append(
                        {
                            **asdict(lane),
                            "live": True,
                            "running": status["running"],
                            "waiting": bool(status["waiting_for"]),
                            "turns": status["turns"],
                            "dollars": status["dollars"],
                        }
                    )
                    continue
                try:
                    info = store.get(lane.session_id)
                    turns, spent = info.turns, float(info.usage.get("dollars", 0.0))
                except SessionError:
                    turns, spent = 0, 0.0
                lanes.append(
                    {
                        **asdict(lane),
                        "live": False,
                        "running": False,
                        "waiting": False,
                        "turns": turns,
                        "dollars": spent,
                    }
                )
        finally:
            store.close()
        return {
            **race.as_json(),
            "lanes": lanes,
            "dollars": sum(lane["dollars"] for lane in lanes),
        }

    async def keep_race(self, race_id: str, session_id: str) -> list[Change]:
        """Copy what one of a race's sessions changed back into the race's project. Raises
        RaceError, or Busy while that session is working."""
        home = self.settings.config.home
        race = races.load(home, race_id)
        lane = next((lane for lane in race.lanes if lane.session_id == session_id), None)
        if lane is None:
            raise races.RaceError(f"{session_id} isn't one of race {race_id}'s sessions.")
        live = self.live.get(session_id) or await self.resume(session_id)
        if live.running:
            raise Busy("Wait for it to finish before keeping its result.")
        checkpoints = live.opened.checkpoints
        if checkpoints is None or not checkpoints.available:
            raise races.RaceError("Its changes can't be found: checkpoints are off.")
        changes, _ = await checkpoints.since_start()
        kept = await asyncio.to_thread(races.keep, race, lane, changes)
        race.kept = session_id
        races.save(home, race)
        return kept

    async def chat(self, model: str | None = None) -> LiveSession:
        """A new chat: no project folder, and none of Zwans's tools."""
        return await self._open(workspace=Path("."), chat=True, model=model)

    async def demo(self, mode: str | None = None) -> LiveSession:
        """A new demo session, in a fresh copy of the demo project."""
        pace = self.settings.demo_pace
        return await self._open(
            workspace=zwans_demo.copy_project(),
            mode=mode,
            model=zwans_demo.MODEL,
            config=zwans_demo.config(self.settings.config),
            make_provider=lambda _config, _model: zwans_demo.provider(pace),
            demo=True,
        )

    def saved_id(self, id_or_prefix: str) -> str:
        """Raises SessionError if no saved session matches."""
        store = SessionStore(self.settings.config.home / "sessions.db")
        try:
            return store.get(id_or_prefix).id
        finally:
            store.close()

    async def _open(
        self,
        config: Config | None = None,
        make_provider: ProviderFactory | None = None,
        demo: bool = False,
        **kwargs: Any,
    ) -> LiveSession:
        opened = open_session(
            config or self.settings.config,
            self.settings.env,
            make_provider=make_provider or self.settings.make_provider,
            ask_later=True,  # the live session gives it its asker, in LiveSession
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
        if demo:
            warnings.insert(0, zwans_demo.NOTE)
        live = LiveSession(opened, warnings, demo)
        self.live[live.id] = live
        return live

    async def rewind(self, session_id: str, turn: int) -> Rewound:
        """Put the workspace's files back as they were before `turn`, and reopen the session
        with its conversation ending just before it, as /undo and /rewind do in the chat.
        Raises KeyError when the session isn't open, Busy, or RewindError."""
        async with self._opening:
            live = self.live[session_id]
            if live.running:
                raise Busy("Stop the running turn before going back.")
            problem = live.undo_problem()
            if problem:
                raise RewindError(problem)
            session, checkpoints = live.opened.session, live.opened.checkpoints
            assert checkpoints is not None
            if turn > session.turn or turn not in await checkpoints.turns():
                raise RewindError(f"There's no checkpoint from before turn {turn}.")
            earliest = session.earliest_turn()
            if 0 < turn - 1 < earliest:
                raise RewindError(
                    f"Turns before {earliest} were summarized, so the earliest to go back to is "
                    f"{earliest}."
                )
            draft = session.prompt_of(turn)
            try:
                undone = await checkpoints.restore(turn)
            except (CheckpointError, OSError) as exc:
                raise RewindError(f"Couldn't put the files back: {exc}") from exc
            mode, model = live.opened.policy.policy.mode, live.opened.model
            await self.close(session_id)
            reopened = await self._open(
                workspace=Path("."), resume=session_id, rewind=turn - 1, mode=mode, model=model
            )
            return Rewound(reopened, undone, draft)

    async def close(self, session_id: str) -> None:
        live = self.live.pop(session_id, None)
        if live is not None:
            await live.close()

    async def delete(self, session_id: str) -> None:
        """Delete a saved session for good: its conversation, its transcript and the tool
        output kept for it. An open one is closed first. Raises Busy while it's working, and
        SessionError when there's no such session. The files it changed, and the checkpoints
        that could undo them, stay."""
        live = self.live.get(session_id)
        if live is not None and live.running:
            raise Busy("Stop the turn before deleting the session.")
        await self.close(session_id)  # which already deletes one nothing was said in
        home = self.settings.config.home
        store = SessionStore(home / "sessions.db")
        try:
            try:
                info = store.get(session_id)
            except SessionError:
                if live is None:
                    raise
                info = None
            if info is not None and info.id != session_id:  # only the start of another's id
                raise SessionError(f"No saved session has the id {session_id!r}.")
            if info is not None:
                store.delete(info.id)
        finally:
            store.close()
        usage.archive(home, session_id)  # what it spent stays counted
        (home / "transcripts" / f"{session_id}.jsonl").unlink(missing_ok=True)
        shutil.rmtree(home / "tool-output" / session_id, ignore_errors=True)
        if info is not None and is_chat(info.workspace, home):
            with contextlib.suppress(OSError):
                Path(info.workspace).rmdir()  # a chat's folder is an empty placeholder

    def mark(self, session_id: str, *, name: str | None = None, pinned: bool | None = None) -> None:
        """Rename or pin a saved session, by its exact id. An open one tells its clients.
        Raises SessionError when there's no such session."""
        store = SessionStore(self.settings.config.home / "sessions.db")
        try:
            info = store.get(session_id)
            if info.id != session_id:
                raise SessionError(f"No saved session has the id {session_id!r}.")
            store.mark(session_id, name=name, pinned=pinned)
            info = store.get(session_id)
        finally:
            store.close()
        live = self.live.get(session_id)
        if live is not None:
            live.opened.info.name, live.opened.info.pinned = info.name, info.pinned
            live._broadcast(live.status())

    async def close_all(self) -> None:
        for session_id in list(self.live):
            await self.close(session_id)


def _earlier_events(path: Path) -> list[Message]:
    """What a resumed session did before, from its transcript, without the turns a rewind
    dropped."""
    events: list[Message] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # a line cut short when Zwans was killed
        if not isinstance(record, dict):
            continue
        if record.get("type") == "rewound":
            cut = _first_turn_after(events, int(record.get("turn") or 0))
            del events[cut:]
        else:
            events.append(record)
    return events


def _first_turn_after(events: list[Message], turn: int) -> int:
    """Where the first turn after `turn` starts in `events`, or the end when there's none.
    Transcripts from before turns were numbered count them instead."""
    count = 0
    for index, event in enumerate(events):
        if event.get("type") == "turn_started":
            count += 1
            if (event.get("turn") or count) > turn:
                return index
    return len(events)
