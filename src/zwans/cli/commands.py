"""Slash commands in the chat: things for Zwans itself rather than for the model."""

from dataclasses import dataclass

import typer

from zwans.checkpoints import Change, CheckpointError
from zwans.cli.input import MENTIONED, Command
from zwans.events import ContextCompacted
from zwans.messages import TextBlock
from zwans.pricing import price_of
from zwans.runtime import OpenedSession
from zwans.session import Session

COMMANDS = [
    Command("help", "List these commands"),
    Command("clear", "Start a new session in this workspace"),
    Command("undo", "Undo the last turn: its file changes and its messages"),
    Command("rewind", "List the turns, or go back to before one", "[turn]"),
    Command("compact", "Summarize the older messages now, to free up context"),
    Command("model", "Show the model, or switch to another", "[name]"),
    Command("cost", "What this session has cost, and how full its context is"),
    Command("resume", "List recent sessions here, or switch to one", "[number or id]"),
    Command("exit", "Quit"),
]
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


type Outcome = Reopen | Quit | None


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
        name, _, argument = line.strip()[1:].partition(" ")
        argument = argument.strip()
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
                self._model(argument)
            case "cost":
                self._cost()
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
        turns = {t: c for t, c in (await checkpoints.turns()).items() if t <= session.turn}
        if not argument:
            await self._list_turns(sorted(turns)[-TURNS_SHOWN:])
            return None
        if not argument.isdigit() or int(argument) not in turns:
            what = "Nothing to undo yet." if undo else f"There's no turn {argument} to go back to."
            _say(what, fg="yellow")
            return None
        turn = int(argument)
        first = min((m.turn for m in session.messages if m.turn is not None), default=1)
        if 0 < turn - 1 < first:
            _say(f"Turns before {first} were summarized, so the earliest to go back to is {first}.")
            return None
        try:
            undone = await checkpoints.restore(turn)
        except CheckpointError as exc:
            _say(f"Couldn't put the files back: {exc}", fg="red")
            return None
        if undone:
            _say(f"Put back {_describe(undone, reverse=True)}.")
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
            prompt = _prompt_of(self.opened.session, turn).split("\n")[0][:60]
            typer.echo(f"  {turn:>3}. {prompt}")
            typer.secho(f"       {changed}", dim=True)
        _say(
            "/rewind <turn> puts the files back as they were before it and drops it and later "
            "turns from the conversation."
        )

    def _help(self) -> None:
        for command in COMMANDS:
            usage = f"/{command.name} {command.argument}".strip()
            typer.echo(f"  {usage:<26} {command.help}")
        _say("Start a message with @path to send a file's text with it.")

    async def _compact(self) -> None:
        session = self.opened.session
        if session.compactor is None:
            _say("This session doesn't compact.", fg="yellow")
            return
        events = await session.compactor.compact(session.messages)
        for event in events:
            session.emit(event)  # the renderer shows it, and the saved session is rewritten
        if not any(isinstance(event, ContextCompacted) for event in events):
            _say("Nothing to compact yet: the conversation is too short.")

    def _model(self, name: str) -> None:
        if not name:
            current = self.opened.model
            _say(f"Model: {current}. /model <name> switches, e.g. /model claude-sonnet-5-5.")
            return
        switch = getattr(self.opened.session.provider, "set_model", None)
        if switch is None:
            _say("This session's provider can't switch models.", fg="yellow")
            return
        if price_of(name) is None:
            _say(f"Zwans doesn't know {name}'s price, so its cost won't be counted.", fg="yellow")
        switch(name)
        self.opened.model = name
        self.opened.store.set_model(self.opened.id, name)
        _say(f"Switched to {name}. Its first reply reads the whole conversation without the cache.")

    def _cost(self) -> None:
        opened = self.opened
        _say(f"Session: {opened.meter.summary()}")
        _say(
            f"Context: about {opened.session.context_tokens():,} tokens, compacting at "
            f"{opened.config.compact_at:,}"
        )

    def _resume(self, argument: str) -> Outcome:
        if argument:
            if argument.isdigit() and 0 < int(argument) <= len(self._listed):
                return Reopen(resume=self._listed[int(argument) - 1])
            return Reopen(resume=argument)
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
            typer.echo(f"  {number:>2}. {when}  {turns:>9}  {info.title}")
        _say("/resume <number> switches to one.")
        return None


def _prompt_of(session: Session, turn: int) -> str:
    """What the user wrote to start `turn`, without the files @mentions added."""
    for message in session.messages:
        if message.role == "user" and message.turn == turn:
            text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
            return text.split(MENTIONED)[0]
    return ""


def _describe(changes: list[Change], reverse: bool = False, shown: int = 4) -> str:
    """ "calc.py (changed), notes.md (added)", and how many more. With `reverse`, the changes
    are the undoing of a turn's, so they're named for what the turn did."""
    flipped = {"added": "deleted", "deleted": "added"} if reverse else {}
    parts = [f"{c.path} ({flipped.get(c.status, c.status)})" for c in changes[:shown]]
    if len(changes) > shown:
        parts.append(f"{len(changes) - shown} more")
    return ", ".join(parts)


def _say(text: str, **style: object) -> None:
    typer.secho(text, dim=not style, **style)  # type: ignore[arg-type]
