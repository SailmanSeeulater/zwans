"""The chat's input line: history, multi-line editing, and completion for commands and files.

Enter sends. Esc then Enter, or Ctrl+J, starts a new line, and pasted text keeps its lines.
Up and Down walk through earlier messages, which are kept in ~/.zwans/history across
sessions. Tab completes a /command at the start, or an @path anywhere.

An @path names a file in the workspace: its text goes along with the message, so the model
doesn't spend a step reading it. A folder sends its listing.
"""

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, History, InMemoryHistory
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.output import Output

MENTION = re.compile(r"(?<!\S)@(\S+)")
TRAILING = ",.;:!?)]}'\""  # punctuation after a mention, as in "look at @calc.py."
MAX_FILE_CHARS = 100_000  # a bigger file is named but not sent; the model can Read parts of it
MAX_LISTING = 200
MENTIONED = "\n\nThe files I mentioned, as they are now:\n\n"  # between a message and its files
SKIPPED_FOLDERS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".next"})


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    argument: str = ""  # shown in /help, as "/model [name]"


@dataclass
class Mentions:
    """What a message's @paths brought in."""

    text: str  # the message with the files' contents after it
    files: list[str] = field(default_factory=list)  # workspace-relative paths that were sent
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
        hints = "Enter sends · Esc Enter new line · @ file · / commands"
        status = self._status()
        return FormattedText([("", f" {status} · {hints}" if status else f" {hints}")])
