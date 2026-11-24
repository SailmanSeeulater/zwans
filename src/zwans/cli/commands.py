"""Slash commands in the chat: things for Zwans itself rather than for the model."""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import typer

from zwans import custom_commands, planning
from zwans.budget import parse_dollars
from zwans.checkpoints import Change, CheckpointError
from zwans.cli.approval import can_prompt, prompt_line
from zwans.cli.input import MENTIONED, Command
from zwans.cli.terminal_text import printable
from zwans.config import Config, ConfigError
from zwans.events import ContextCompacted
from zwans.looping import parse_loop, run_loop
from zwans.providers.base import ProviderError
from zwans.providers.catalog import CLAUDE_MODELS, PRESETS, canonical, is_known, list_all, split
from zwans.providers.router import ModelRouter
from zwans.runtime import OpenedSession
from zwans.session import Session
from zwans.store import SessionError

COMMANDS = [
    Command("help", "List these commands"),
    Command("clear", "Start a new session in this workspace"),
    Command("undo", "Undo the last turn: its file changes and its messages"),
    Command("rewind", "List the turns, or go back to before one", "[turn]"),
    Command("compact", "Summarize the older messages now, to free up context"),
    Command(
        "model",
        "Show the model, or switch to another",
        "[name]",
        choices=(*CLAUDE_MODELS, *(f"{name}/" for name in PRESETS)),
    ),
    Command("cost", "What this session has cost, and how full its context is"),
    Command("budget", "Show the spending cap, or set one ($2, or off)", "[dollars]"),
    Command(
        "loop",
        "Keep working until a check passes, such as: /loop until pytest -q",
        "[rounds] until <check> [task]",
    ),
    Command(
        "plan",
        "Plan first: the model looks and proposes, and nothing changes until /go",
        "[task | off]",
    ),
    Command("go", "Carry out the plan: plan mode goes off"),
    Command("resume", "List recent sessions here, or switch to one", "[number or id]"),
    Command("exit", "Quit"),
]
KNOWN = {command.name for command in COMMANDS} | {"quit"}
RECENT_SHOWN = 10
TURNS_SHOWN = 10


@dataclass(frozen=True)
class Reopen:
    """Close this session and open another: a saved one, or a new one when resume is None.
    With `rewind`, the saved one first drops every turn after that one; `draft` goes in the
    input line, as the prompt of the turn that was undone."""

    resume: str | None
    rewind: int | None = None
    draft: str = ""


@dataclass(frozen=True)
class Quit:
    pass


@dataclass(frozen=True)
class Send:
    """Send this to the model, as if it had been typed: what a command of your own says."""

    text: str


type Outcome = Reopen | Quit | Send | None


def is_command(line: str) -> bool:
    """A message is a command when its first word is "/" and a name, as in "/model opus".
    A path such as "/etc/hosts is wrong" has a second slash, so it goes to the model."""
    first = line.split(maxsplit=1)[0] if line.strip() else ""
    return first.startswith("/") and len(first) > 1 and "/" not in first[1:]


class Commands:
    def __init__(self, opened: OpenedSession) -> None:
        self.opened = opened
        self._listed: list[str] = []  # the ids /resume last showed, so "/resume 2" works

    async def run(self, line: str) -> Outcome:
        first, _, rest = line.strip().partition("\n")
        name, _, argument = first[1:].partition(" ")
        argument = argument.strip()
        if name not in KNOWN:
            return await self._custom(name, f"{argument}\n{rest}".strip())
        if name == "plan":  # the task may run to several lines
            return self._plan(f"{argument}\n{rest}".strip())
        if rest.strip() and name in KNOWN:
            # Likely lines typed ahead that ran together: doing only part of it would surprise.
            _say(f"/{name} goes on a line of its own, so nothing was done.", fg="yellow")
            return None
        match name:
            case "help":
                self._help()
            case "clear":
                return Reopen(resume=None)
            case "undo":
                return await self._rewind(str(self.opened.session.turn), undo=True)
            case "rewind":
                return await self._rewind(argument)
            case "compact":
                await self._compact()
            case "model":
                await self._model(argument)
            case "cost":
                self._cost()
            case "budget":
                self._budget(argument)
            case "loop":
                await self._loop(argument)
            case "go":
                return self._go()
            case "resume":
                return self._resume(argument)
            case "exit" | "quit":
                return Quit()
            case _:
                _say(f"There's no /{name}. /help lists the commands.", fg="yellow")
        return None

    async def _rewind(self, argument: str, undo: bool = False) -> Outcome:
        checkpoints = self.opened.checkpoints
        if checkpoints is None or not checkpoints.available:
            off = "Checkpoints are off (checkpoints = false)."
            _say(f"{checkpoints.problem if checkpoints else off} So turns can't be undone.")
            return None
        session = self.opened.session
        try:
            turns = {t: c for t, c in (await checkpoints.turns()).items() if t <= session.turn}
            if not argument:
                await self._list_turns(sorted(turns)[-TURNS_SHOWN:])
                return None
        except CheckpointError as exc:  # such as when the workspace was moved
            _say(f"Couldn't read the checkpoints: {printable(str(exc))}", fg="red")
            return None
        if not argument.isdigit() or int(argument) not in turns:
            what = "Nothing to undo yet." if undo else f"There's no turn {argument} to go back to."
            _say(what, fg="yellow")
            return None
        turn = int(argument)
        first = session.earliest_turn()
        if 0 < turn - 1 < first:
            _say(f"Turns before {first} were summarized, so the earliest to go back to is {first}.")
            return None
        try:
            undone = await checkpoints.restore(turn)
        except (CheckpointError, OSError) as exc:
            _say(f"Couldn't put the files back: {printable(str(exc))}", fg="red")
            return None
        if undone:
            _say(_describe_undo(undone))
        else:
            _say("No files had changed since then.")
        return Reopen(resume=self.opened.id, rewind=turn - 1, draft=_prompt_of(session, turn))

    async def _list_turns(self, turns: list[int]) -> None:
        checkpoints = self.opened.checkpoints
        assert checkpoints is not None
        if not turns:
            _say("No turns to go back to yet.")
            return
        for turn in turns:
            changes = await checkpoints.changes(turn)
            changed = _describe(changes) if changes else "no file changes"
            prompt = printable(_prompt_of(self.opened.session, turn).split("\n")[0][:60])
            typer.echo(f"  {turn:>3}. {prompt}")
            typer.secho(f"       {changed}", dim=True)
        _say(
            "/rewind <turn> puts the files back as they were before it and drops it and later "
            "turns from the conversation."
        )

    def custom(self) -> tuple[dict[str, custom_commands.CustomCommand], list[str]]:
        """Your commands and the project's, read again each time so an edit shows at once."""
        workspace = None if self.opened.chat else Path(self.opened.info.workspace)
        return custom_commands.load(workspace, self.opened.config.home, KNOWN)

    async def _custom(self, name: str, argument: str) -> Outcome:
        found, problems = self.custom()
        command = found.get(name)
        if command is None:
            broken = [p for p in problems if p.startswith(f"{name}.md")]
            _say(
                broken[0] if broken else f"There's no /{name}. /help lists the commands.",
                fg="yellow",
            )
            return None
        if not command.check:
            return Send(custom_commands.expand(command, argument))
        home = self.opened.config.home
        if command.needs_trust(home):
            _say(
                f"{command.path} came with this project and runs `{printable(command.check)}` "
                "after each turn.",
                fg="yellow",
            )
            if not can_prompt() or prompt_line("Trust this file? [y/N]: ").lower() not in (
                "y",
                "yes",
            ):
                _say("Not run. /loop runs a check you type yourself.", fg="yellow")
                return None
            command.trust(home)
        spec = custom_commands.loop_spec(command, argument)
        _say(f"Looping until `{spec.check}` passes, for at most {spec.rounds} turns.", dim=True)
        await run_loop(self.opened.session, self.opened.executor, spec)
        return None

    def _help(self) -> None:
        for command in COMMANDS:
            usage = f"/{command.name} {command.argument}".strip()
            typer.echo(f"  {usage:<26} {command.help}")
        found, problems = self.custom()
        if found:
            typer.echo()
            for custom in found.values():
                usage = f"/{custom.name} {custom.args}".strip()
                where = "project" if custom.scope == "project" else "yours"
                typer.echo(f"  {usage:<26} {printable(custom.description)} ({where})")
        for problem in problems:
            _say(printable(problem), fg="yellow")
        _say("Start a message with @path to send a file's text, or an image, with it.")

    async def _compact(self) -> None:
        session = self.opened.session
        if session.compactor is None:
            _say("This session doesn't compact.", fg="yellow")
            return
        if not session.compactor.can_compact(session.messages):
            _say("Nothing to compact yet: the conversation is too short.")
            return
        _say("Compacting: the model is summarizing the older messages...")  # it takes a while
        try:
            events = await session.compactor.compact(session.messages)
        except ProviderError as exc:
            _say(f"Couldn't compact: {exc}", fg="red")
            return
        for event in events:
            session.emit(event)  # the renderer shows it, and the saved session is rewritten
        if not any(isinstance(event, ContextCompacted) for event in events):
            _say("The model wrote no summary, so nothing was compacted.", fg="yellow")

    async def _model(self, name: str) -> None:
        current = self.opened.model
        router = self.opened.session.provider
        if not name:
            _say(f"Model: {current}. /model <name> switches to another, such as:")
            if isinstance(router, ModelRouter):
                await _print_models(router.config, router.env, current)
            else:
                for known in CLAUDE_MODELS:
                    typer.echo(f"  {known}{'  (current)' if known == current else ''}")
            return
        switch = getattr(router, "set_model", None)
        if switch is None:
            _say("This session's provider can't switch models.", fg="yellow")
            return
        name = canonical(name)
        if split(name)[0] is None:
            _say(
                f"{name} doesn't say where it runs. Name other models as <provider>/<model>, "
                f"as ollama/{name}; /model lists what's available.",
                fg="yellow",
            )
            return
        if not is_known(name):
            # A typo would only show up as an API error on the next turn, and stay saved.
            _say(f"Zwans doesn't know {name}. /model lists the models it knows.", fg="yellow")
            model = shlex.quote(name)
            if self.opened.empty:  # deleted on quitting, so there'd be nothing to resume
                workspace = shlex.quote(self.opened.info.workspace)
                _say(f"To use it anyway, start a new session: zwans -w {workspace} --model {model}")
            else:
                _say(f"To use it anyway: zwans --resume {self.opened.id} --model {model}")
            return
        try:
            switch(name)
        except ConfigError as exc:
            _say(str(exc), fg="yellow")
            return
        if not isinstance(router, ModelRouter):  # a scripted provider, in tests
            self.opened.model = name
            self.opened.store.set_model(self.opened.id, name)
            _say(f"Switched to {name}.")
            return
        self.opened.model = router.model
        self.opened.store.set_model(self.opened.id, router.model)
        note = "Its first reply reads the whole conversation without the cache."
        if router.resolved.provider != "anthropic":
            note = (
                "Its first reply reads the whole conversation. Claude's web search isn't "
                "offered to it."
            )
        _say(f"Switched to {router.model}. {note}")

    def _cost(self) -> None:
        opened = self.opened
        _say(f"Session: {opened.meter.summary()}")
        _say(
            f"Context: about {opened.session.context_tokens():,} tokens, compacting at "
            f"{opened.session.compact_at(opened.config.compact_at):,}"
        )

    def _budget(self, argument: str) -> None:
        budget = self.opened.budget
        if budget is None:
            _say("This session has no budget to set.", fg="yellow")
            return
        if argument:
            try:
                budget.dollars = parse_dollars(argument)
            except ValueError:
                _say(f"{argument} isn't an amount: try /budget 2, /budget $0.50 or /budget off.")
                return
        _say(budget.describe())
        if budget.exceeded():
            _say("Turns stop before their next model call until it's raised.", fg="yellow")

    async def _loop(self, argument: str) -> None:
        try:
            spec = parse_loop(argument)
        except ValueError as exc:
            _say(str(exc), fg="yellow")
            return
        _say(f"Looping until `{spec.check}` passes, for at most {spec.rounds} turns.", dim=True)
        await run_loop(self.opened.session, self.opened.executor, spec)

    def _plan(self, argument: str) -> Outcome:
        session = self.opened.session
        if argument.lower() == "off":
            if session.set_planning(False):
                _say("Plan mode is off: changes are judged by the permissions as before.")
            else:
                _say("Plan mode isn't on.")
            return None
        if session.permissions is None:
            _say("Plan mode needs a session that checks its tool calls.", fg="yellow")
            return None
        if session.set_planning(True):
            _say(
                "Plan mode: the model can look but not change anything. When its plan looks "
                "right, /go carries it out; /plan off leaves without it."
            )
        elif not argument:
            _say("Plan mode is already on. /go carries out the plan; /plan off leaves.")
        return Send(argument) if argument else None

    def _go(self) -> Outcome:
        if not self.opened.session.set_planning(False, approved=True):
            _say("There's no plan to carry out: /plan <task> asks for one first.")
            return None
        return Send(planning.GO)

    def _resume(self, argument: str) -> Outcome:
        if argument:
            if argument.isdigit() and 0 < int(argument) <= len(self._listed):
                return Reopen(resume=self._listed[int(argument) - 1])
            if argument.isdigit() and int(argument) <= RECENT_SHOWN:  # not the start of an id
                _say(f"There's no session {argument} in the list. /resume lists them.", fg="yellow")
                return None
            try:  # check first, since switching closes this session
                info = self.opened.store.get(argument)
            except SessionError as exc:
                _say(str(exc), fg="yellow")
                return None
            if info.id == self.opened.id:
                _say("That's this session.")
                return None
            return Reopen(resume=info.id)
        workspace = self.opened.info.workspace
        found = [
            info
            for info in self.opened.store.recent(limit=100)
            if info.workspace == workspace and info.id != self.opened.id and info.turns
        ][:RECENT_SHOWN]
        if not found:
            _say("No other sessions in this workspace yet.")
            return None
        self._listed = [info.id for info in found]
        for number, info in enumerate(found, start=1):
            when = info.updated_at.replace("T", " ")[:16]
            turns = f"{info.turns} turn{'s' if info.turns != 1 else ''}"
            # The title is the start of the first prompt, which may hold escape codes.
            typer.echo(f"  {number:>2}. {when}  {turns:>9}  {printable(info.label)}")
        _say("/resume <number> switches to one.")
        return None


def _prompt_of(session: Session, turn: int) -> str:
    """What the user wrote to start `turn`, without the files @mentions added."""
    return session.prompt_of(turn).split(MENTIONED)[0]


def _describe(changes: list[Change]) -> str:
    """ "calc.py (changed), notes.md (added)", and how many more."""
    # Names come from git unquoted, and a file can be named with escape codes.
    return _names([f"{printable(c.path)} ({c.status})" for c in changes])


def _describe_undo(undone: list[Change]) -> str:
    """What going back did to the files, as "Removed notes.md, which was new; restored calc.py
    to how it was." The changes are the undoing's, so a file it deleted was a new one."""
    removed = [printable(c.path) for c in undone if c.status == "deleted"]
    restored = [printable(c.path) for c in undone if c.status != "deleted"]
    parts = []
    if removed:
        parts.append(f"removed {_names(removed)}, which {_was(removed)} new")
    if restored:
        they = "it" if len(restored) == 1 else "they"
        parts.append(f"restored {_names(restored)} to how {they} {_was(restored)}")
    text = "; ".join(parts)
    return f"{text[0].upper()}{text[1:]}."


def _names(items: list[str], shown: int = 4) -> str:
    """The first few, and how many more."""
    parts = items[:shown]
    if len(items) > shown:
        parts.append(f"{len(items) - shown} more")
    return ", ".join(parts)


def _was(items: list[str]) -> str:
    return "was" if len(items) == 1 else "were"


def _say(text: str, **style: object) -> None:
    typer.secho(text, **{"dim": not style, **style})  # type: ignore[arg-type]


async def _print_models(config: Config, env: Mapping[str, str], current: str) -> None:
    """What each provider offers, as `zwans models` shows it, marking the current model."""
    for listing in await list_all(config, env):
        if not listing.models and listing.local and listing.note == "not running":
            continue  # a local server that isn't installed or started: noise here
        about = f"  ({listing.note})" if listing.note else ""
        typer.secho(f"  {listing.provider}: {listing.about}{about}", dim=not listing.ready)
        for model in listing.models:
            typer.echo(f"    {model}{'  (current)' if model == current else ''}")
    _say("Other providers' models: <provider>/<model>. `zwans models` lists them all.")
