"""The chat's input line: history, multi-line editing, and completion for commands and files.

Enter sends. Esc then Enter, or Ctrl+J, starts a new line, and pasted text keeps its lines.
Up and Down walk through earlier messages, which are kept in ~/.zwans/history across
sessions. Tab completes a /command at the start, or an @path anywhere. What's typed while a
turn runs waits, unechoed: once the prompt is back, each line of it is sent in turn, and a
paste as one message.

An @path names a file in the workspace: its text goes along with the message, so the model
doesn't spend a step reading it. A folder sends its listing.
"""

import asyncio
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from prompt_toolkit.input import Input
from prompt_toolkit.input.typeahead import store_typeahead
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.key_processor import KeyPress
from prompt_toolkit.output import Output

from zwans.images import ImageError, image_block, media_type
from zwans.messages import ImageBlock

if sys.platform != "win32":
    import termios

MENTION = re.compile(r"(?<!\S)@(\S+)")
TRAILING = ",.;:!?)]}'\""  # punctuation after a mention, as in "look at @calc.py."
MAX_FILE_CHARS = 100_000  # a bigger file is named but not sent; the model can Read parts of it
MAX_LISTING = 200
MENTIONED = "\n\nThe files I mentioned, as they are now:\n\n"  # between a message and its files
PASTE_ON, PASTE_OFF = "\x1b[?2004h", "\x1b[?2004l"  # the terminal's bracketed paste mode
SKIPPED_FOLDERS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".next"})
HINTS = ("Enter sends", "Esc Enter new line", "@ file", "/ commands")


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    argument: str = ""  # shown in /help, as "/model [name]"
    choices: tuple[str, ...] = ()  # what Tab completes the argument to


@dataclass
class Mentions:
    """What a message's @paths brought in."""

    text: str  # the message with the files' contents after it
    files: list[str] = field(default_factory=list)  # workspace-relative paths that were sent
    images: list[ImageBlock] = field(default_factory=list)  # from mentioned image files
    problems: list[str] = field(default_factory=list)  # @paths that couldn't be sent


def expand_mentions(message: str, workspace: Path) -> Mentions:
    """Add the contents of each @path in the workspace to the message. An @word that isn't a
    path there is left alone: it may be a handle or a decorator."""
    root = workspace.resolve()
    result = Mentions(text=message)
    blocks: list[str] = []
    for match in MENTION.finditer(message):
        name = match.group(1).rstrip(TRAILING)
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.exists():
            continue
        relative = path.relative_to(root).as_posix() or "."
        if relative in result.files:
            continue
        if path.is_dir():
            blocks.append(f'<folder path="{relative}">\n{_listing(path)}\n</folder>')
        elif _is_image(path):
            try:
                result.images.append(image_block(path.read_bytes(), f"@{name}"))
            except (OSError, ImageError) as exc:
                result.problems.append(str(exc))
                continue
        else:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                result.problems.append(f"@{name} isn't a text file, so it wasn't sent.")
                continue
            if len(text) > MAX_FILE_CHARS:
                result.problems.append(
                    f"@{name} is {len(text):,} characters, too long to send; the model can Read it."
                )
                continue
            blocks.append(f'<file path="{relative}">\n{text}\n</file>')
        result.files.append(relative)
    if blocks:
        joined = "\n\n".join(blocks)
        result.text = f"{message}{MENTIONED}{joined}"
    return result


def _is_image(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return media_type(file.read(16)) is not None
    except OSError:
        return False


def _listing(folder: Path) -> str:
    entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    names = [
        f"{p.name}/" if p.is_dir() else p.name for p in entries if p.name not in SKIPPED_FOLDERS
    ]
    if len(names) > MAX_LISTING:
        names = [*names[:MAX_LISTING], f"... and {len(names) - MAX_LISTING} more"]
    return "\n".join(names) or "(empty)"


class ChatCompleter(Completer):
    """Completes a /command at the start of the message, and an @path anywhere in it."""

    def __init__(self, commands: Sequence[Command], workspace: Path) -> None:
        self.commands = commands
        self.workspace = workspace.resolve()

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        before = document.text_before_cursor
        if before.startswith("/") and " " not in before:
            for command in self.commands:
                if command.name.startswith(before[1:]):
                    yield Completion(f"/{command.name}", -len(before), display_meta=command.help)
            return
        name, _, typed = before[1:].partition(" ")
        choices = [c for command in self.commands if command.name == name for c in command.choices]
        if before.startswith("/") and choices and not any(c.isspace() for c in typed):
            for choice in choices:
                if choice.startswith(typed):
                    yield Completion(choice, -len(typed))
            return
        word = before.split()[-1] if before and not before[-1].isspace() else ""
        if word.startswith("@"):
            yield from self._paths(word[1:])

    def _paths(self, typed: str) -> Iterable[Completion]:
        folder_part, _, prefix = typed.rpartition("/")
        folder = (self.workspace / folder_part).resolve()
        if not folder.is_relative_to(self.workspace) or not folder.is_dir():
            return
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.name in SKIPPED_FOLDERS or not entry.name.startswith(prefix):
                continue
            if entry.name.startswith(".") and not prefix.startswith("."):
                continue
            name = f"{folder_part}/{entry.name}" if folder_part else entry.name
            suffix = "/" if entry.is_dir() else ""
            yield Completion(f"@{name}{suffix}", -len(typed) - 1, display=f"{entry.name}{suffix}")


def key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _send(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.complete_state and buffer.complete_state.current_completion:
            buffer.apply_completion(buffer.complete_state.current_completion)
        else:
            buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    @bindings.add("c-j")
    def _new_line(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("c-c")
    def _clear_or_quit(event: KeyPressEvent) -> None:
        """Ctrl+C clears what's typed; on an empty line it quits."""
        buffer = event.current_buffer
        if buffer.text:
            buffer.reset()
        else:
            event.app.exit(exception=KeyboardInterrupt())

    return bindings


class Composer:
    """Reads the user's next message."""

    def __init__(
        self,
        commands: Sequence[Command],
        workspace: Path,
        history_path: Path | None,
        status: Callable[[], str] = lambda: "",
        input: Input | None = None,
        output: Output | None = None,
    ) -> None:
        history: History = InMemoryHistory()
        if history_path is not None:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_path))
        self._status = status
        self._typed: bytearray | None = None  # what's typed ahead, while a turn runs
        self._session: PromptSession[str] = PromptSession(
            history=history,
            completer=ChatCompleter(commands, workspace),
            complete_while_typing=True,
            key_bindings=key_bindings(),
            multiline=True,  # Enter is bound above, so it still sends
            prompt_continuation="  ",
            bottom_toolbar=self._toolbar,
            input=input,
            output=output,
        )

    async def read(self, draft: str = "") -> str:
        """The next message, starting from `draft`. Raises EOFError (Ctrl+D) or
        KeyboardInterrupt (Ctrl+C on an empty line) when the user wants to stop."""
        return await self._session.prompt_async(FormattedText([("bold", "> ")]), default=draft)

    def _toolbar(self) -> FormattedText:
        width = self._session.app.output.get_size().columns
        return FormattedText([("", toolbar_line(self._status(), width))])

    @contextmanager
    def typing_ahead(
        self,
        loop: asyncio.AbstractEventLoop,
        stream: TextIO | None = None,
        out: TextIO | None = None,
    ) -> Iterator[None]:
        """While a turn runs on `loop`, keep what the user types for the next prompt instead
        of letting the terminal print it into the output. The prompt then sends each line
        typed ahead as its own message, and a paste as one. It's read as it comes, so a
        long paste isn't cut off at the terminal's input limit. Ctrl+C drops it."""
        stream = stream or sys.stdin
        if sys.platform == "win32" or not stream.isatty():
            yield
            return
        fd = stream.fileno()
        typed = self._typed = bytearray()

        def take() -> None:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if chunk:
                typed.extend(chunk)
            else:  # the terminal went away
                loop.remove_reader(fd)

        with _terminal_input(stream, out or sys.stdout, echo=False):
            loop.add_reader(fd, take)
            try:
                yield
            finally:
                loop.remove_reader(fd)
                self._typed = None
        store_typeahead(self._session.app.input, _key_presses(bytes(typed)))

    def drop_typed_ahead(self) -> bool:
        """Forget what's been typed ahead so far in this turn, as when a question is asked:
        it was typed before the question, so it mustn't answer it, nor become a message that
        answers the model instead. What's typed after this is kept. Says whether there was
        anything to drop."""
        if not self._typed:
            return False
        self._typed.clear()
        return True


def toolbar_line(status: str, width: int) -> str:
    """The status and key hints, cut down to fit a terminal `width` columns wide: hints go
    first, then the status's last parts, so a narrow terminal still shows the model."""
    parts = [*(p for p in status.split(" · ") if p), *HINTS]
    room = max(width - 2, 1)  # a leading space, and the last column, which would wrap
    while len(parts) > 1 and len(" · ".join(parts)) > room:
        parts.pop()
    line = " · ".join(parts)
    if len(line) > room:
        line = line[: room - 1] + "…"
    return f" {line}"


@contextmanager
def echoing(stream: TextIO | None = None, out: TextIO | None = None) -> Iterator[None]:
    """Show typing again for a question asked mid-turn, such as an approval. Only what's
    typed after the question can answer it."""
    with _terminal_input(stream or sys.stdin, out or sys.stdout, echo=True):
        yield


@contextmanager
def _terminal_input(stream: TextIO, out: TextIO, echo: bool) -> Iterator[None]:
    """Hide typing and hand each key over as it comes (echo=False), or show it and read
    whole lines again (echo=True)."""
    if sys.platform == "win32" or not stream.isatty():
        yield
        return
    fd = stream.fileno()
    saved = termios.tcgetattr(fd)
    hidden = not saved[3] & termios.ECHO  # asked inside Composer.typing_ahead()
    changed = [*saved[:6], list(saved[6])]  # a copy of the control characters too
    flags = termios.ECHO | termios.ICANON
    if echo:
        termios.tcflush(fd, termios.TCIFLUSH)
        changed[0] |= termios.ICRNL
        changed[3] |= flags
    else:
        changed[0] &= ~termios.ICRNL
        changed[3] &= ~flags
        changed[6][termios.VMIN], changed[6][termios.VTIME] = 1, 0
    termios.tcsetattr(fd, termios.TCSANOW, changed)
    if hidden or not echo:
        _mark_pastes(out, not echo)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        if hidden or not echo:
            _mark_pastes(out, echo)


def _mark_pastes(out: TextIO, on: bool) -> None:
    """Turn the terminal's bracketed paste on or off: when on, a paste arrives marked, so the
    prompt keeps it as one message even if it has several lines."""
    if out.isatty():
        out.write(PASTE_ON if on else PASTE_OFF)
        out.flush()


def _key_presses(typed: bytes) -> list[KeyPress]:
    keys: list[KeyPress] = []
    parser = Vt100Parser(keys.append)
    parser.feed(typed.decode("utf-8", errors="replace"))
    parser.flush()
    return keys
