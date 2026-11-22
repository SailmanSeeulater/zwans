"""`zwans room`: several agents on different models talking about a topic, in the terminal."""

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from zwans.cli.terminal_text import printable
from zwans.config import ConfigError, load_settings
from zwans.providers.fake import FakeProvider
from zwans.room import (
    ROOMS,
    USER,
    LineAdded,
    ProviderMaker,
    Room,
    RoomError,
    RoomEvent,
    RoomStopped,
    SpeakerStarted,
    SpeakerText,
    load_room,
    parse_agent,
    recent_rooms,
    router_maker,
)

COLOURS = ["cyan", "magenta", "yellow", "green", "blue", "bright_red", "bright_cyan", "white"]
REPLAYED_LINES = 6  # of a resumed room, shown again


def room(
    topic: Annotated[
        str | None, typer.Argument(help="What the agents should talk about.", show_default=False)
    ] = None,
    agent: Annotated[
        list[str] | None,
        typer.Option(
            "--agent",
            "-a",
            help="An agent as name=model, as ada=claude-opus-5-5 or bo=ollama/qwen3:8b. "
            "Give one for each agent; they speak in this order.",
            show_default=False,
        ),
    ] = None,
    persona: Annotated[
        list[str] | None,
        typer.Option(
            help='Who an agent is, as name="a skeptical security reviewer".',
            show_default=False,
        ),
    ] = None,
    turns: Annotated[
        int, typer.Option(min=1, max=200, help="Turns to run before you get to speak.")
    ] = 6,
    budget: Annotated[
        float | None,
        typer.Option(min=0, help="Stop once the room has spent this many dollars in all."),
    ] = None,
    resume: Annotated[
        str | None, typer.Option(help="Continue a saved room: its id, or the start of it.")
    ] = None,
    list_rooms: Annotated[bool, typer.Option("--list", help="List saved rooms and exit.")] = False,
    fake_script: Annotated[
        Path | None,
        typer.Option(hidden=True, help="Replay model responses from a JSON file, for tests."),
    ] = None,
) -> None:
    """Open a room where several agents, each on its own model, talk to each other.

    Agents take turns, and one mentioned as @Name goes next. Rooms have no tools.

    Between runs, say something, press Enter for more turns, or type /quit. Ctrl+C stops one.
    """
    try:
        config, env = load_settings()
    except ConfigError as exc:
        _fail(str(exc))
    folder = config.home / ROOMS
    if list_rooms:
        _list(folder)
        return

    make: ProviderMaker
    if fake_script is not None:
        fake = FakeProvider.from_file(fake_script)  # one script, replayed in speaking order
        make = lambda _model: fake  # noqa: E731
    else:
        make = router_maker(config, env)

    try:
        if resume is not None:
            if agent or persona:
                raise RoomError("A resumed room keeps its own agents; leave out --agent.")
            opened = Room(load_room(folder, resume), make, folder, budget)
        else:
            if not topic:
                raise RoomError('Give the room a topic, as zwans room "Tabs or spaces?".')
            if not agent:
                raise RoomError("Give each agent as --agent name=model, at least one of them.")
            agents = [parse_agent(spec) for spec in agent]
            by_name = {a.name.lower(): a for a in agents}
            for spec in persona or []:
                name, sep, about = spec.partition("=")
                if not sep or name.strip().lower() not in by_name:
                    raise RoomError(f"--persona {spec!r} doesn't name one of the agents.")
                by_name[name.strip().lower()].persona = about.strip()
            opened = Room.new(topic, agents, make, folder, budget)
    except RoomError as exc:
        _fail(str(exc))

    raise typer.Exit(_converse(opened, turns))


def _converse(opened: Room, turns: int) -> int:
    printer = Printer(opened)
    printer.banner()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    failed = False
    with asyncio.Runner() as runner:
        try:
            while True:
                try:
                    failed = runner.run(printer.play(opened.run(turns)))
                except KeyboardInterrupt:
                    typer.secho("\n  Stopped.", dim=True)
                if not interactive:
                    break
                said = _ask()
                if said is None:
                    break
                if said:
                    printer.show(opened.say(said))
        finally:
            runner.run(opened.aclose())
    typer.secho(f"\n{_cost(opened)}. Resume with: zwans room --resume {opened.id}", dim=True)
    return 1 if failed and not interactive else 0


def _ask() -> str | None:
    """What the user says next: text, "" to run more turns, or None to leave."""
    typer.secho(
        "\nSay something (@Name picks who answers), Enter for more turns, /quit to leave.",
        dim=True,
    )
    try:
        line = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return None if line in ("/quit", "/exit", "/q") else line


class Printer:
    def __init__(self, opened: Room) -> None:
        self.room = opened
        self.colours = {a.name: COLOURS[i % len(COLOURS)] for i, a in enumerate(opened.info.agents)}
        self.shown = ""  # what's been printed of the line being spoken

    def banner(self) -> None:
        info = self.room.info
        typer.secho(printable(f"Room {info.id}: {info.topic}"), bold=True)
        for a in info.agents:
            about = f": {a.persona}" if a.persona else ""
            typer.echo("  " + self._name(a.name) + printable(f" · {a.model}{about}"))
        earlier = info.lines[-REPLAYED_LINES:]
        if earlier:
            skipped = len(info.lines) - len(earlier)
            note = f" ({skipped} earlier lines not shown)" if skipped else ""
            typer.secho(f"\nSo far{note}:", dim=True)
            for line in earlier:
                self._header(line.speaker, line.model)
                typer.echo(printable(line.text) + (" [cut off]" if line.cut else ""))

    async def play(self, events: AsyncIterator[RoomEvent]) -> bool:
        """Print a run's events. Returns whether it stopped on an error."""
        failed = False
        async for event in events:
            self.show(event)
            failed = failed or (isinstance(event, RoomStopped) and event.reason == "error")
        return failed

    def show(self, event: RoomEvent) -> None:
        if isinstance(event, SpeakerStarted):
            self._header(event.speaker, event.model)
            self.shown = ""
        elif isinstance(event, SpeakerText):
            sys.stdout.write(printable(event.text))
            sys.stdout.flush()
            self.shown += event.text
        elif isinstance(event, LineAdded):
            line = event.line
            if line.speaker == USER:
                return  # it was typed, so it's on screen already
            rest = line.text[len(self.shown) :] if line.text.startswith(self.shown) else ""
            if not self.shown:
                rest = line.text
            sys.stdout.write(printable(rest) + "\n")
            price = f"${line.dollars:.4f}" if line.dollars is not None else "price unknown"
            typer.secho(f"  {price} · room ${event.dollars:.4f}", dim=True)
            self.shown = ""
        elif isinstance(event, RoomStopped):
            if event.reason == "budget":
                typer.secho(f"\n  {event.detail}", fg="yellow")
            elif event.reason == "error":
                typer.secho(printable(f"\n  {event.detail}"), fg="red")

    def _header(self, speaker: str, model: str) -> None:
        typer.echo("\n" + self._name(speaker) + typer.style(printable(f" · {model}"), dim=True))

    def _name(self, name: str) -> str:
        return typer.style(name, fg=self.colours.get(name, "white"), bold=True)


def _cost(opened: Room) -> str:
    info = opened.info
    text = f"The room has cost ${info.dollars:.4f}"
    if info.unpriced:
        text += f", plus {', '.join(info.unpriced)}, whose price isn't known"
    return text


def _list(folder: Path) -> None:
    rooms = recent_rooms(folder)
    if not rooms:
        typer.echo('No saved rooms yet. Start one with zwans room "<topic>" --agent name=model.')
    for info in rooms:
        when = info.updated_at.replace("T", " ")[:16]
        who = ", ".join(a.name for a in info.agents)
        typer.echo(
            printable(
                f"{info.id}  {when}  {len(info.lines):>4} lines  ${info.dollars:7.4f}  "
                f"{info.topic[:50]}  ({who})"
            )
        )


def _fail(message: str) -> NoReturn:
    typer.secho(printable(message), fg="red", err=True)
    raise typer.Exit(2)
