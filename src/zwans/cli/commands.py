"""Slash commands in the chat: things for Zwans itself rather than for the model."""

from dataclasses import dataclass

import typer

from zwans.cli.input import Command
from zwans.events import ContextCompacted
from zwans.pricing import price_of
from zwans.runtime import OpenedSession

COMMANDS = [
    Command("help", "List these commands"),
    Command("clear", "Start a new session in this workspace"),
    Command("compact", "Summarize the older messages now, to free up context"),
    Command("model", "Show the model, or switch to another", "[name]"),
    Command("cost", "What this session has cost, and how full its context is"),
    Command("resume", "List recent sessions here, or switch to one", "[number or id]"),
    Command("exit", "Quit"),
]
RECENT_SHOWN = 10


@dataclass(frozen=True)
class Reopen:
    """Close this session and open another: a saved one, or a new one when resume is None."""

    resume: str | None


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


def _say(text: str, **style: object) -> None:
    typer.secho(text, dim=not style, **style)  # type: ignore[arg-type]
