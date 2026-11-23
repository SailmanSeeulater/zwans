"""Your own slash commands, from Markdown files: `~/.zwans/commands/<name>.md` works in every
project, and `<project>/.zwans/commands/<name>.md` in that one, winning over yours of the
same name. Typing /<name> sends the file's text as the message, with what follows the name
put in for $ARGUMENTS ($1, $2... for its words).

A file can start with a header between `---` lines:

    ---
    description: Fix what the linter reports
    args: [path]
    loop: ruff check .
    rounds: 6
    ---
    Fix everything `ruff check $ARGUMENTS` reports, without changing behaviour.

With `loop`, the command runs as /loop does: Zwans runs the check after each turn and sends
what fails until it passes. A check in a project's file is a command that came with the
folder, so it only runs once you've trusted that file as it is now, as with a project's
policy hooks; your own files in ~/.zwans/commands need no trusting.
"""

import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from zwans.looping import DEFAULT_ROUNDS, MOST_ROUNDS, LoopSpec
from zwans.policy.rules import is_trusted, trust

FOLDER = "commands"
NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
MOST_BYTES = 64_000  # a prompt, not a document
KEYS = {"description", "args", "argument-hint", "loop", "rounds"}
# Zwans's own commands, in the terminal or the web UI: a file can't take their names.
RESERVED = frozenset(
    {"help", "clear", "undo", "rewind", "compact", "model", "cost", "budget", "loop"}
    | {"resume", "exit", "quit", "replay"}
)

type Scope = Literal["project", "user"]


@dataclass(frozen=True)
class CustomCommand:
    name: str
    path: Path
    scope: Scope
    body: str
    description: str = ""
    args: str = ""  # how to use it, as "[path]"
    check: str = ""  # with one, it loops until the check passes
    rounds: int = DEFAULT_ROUNDS

    def needs_trust(self, home: Path) -> bool:
        """A project's command that runs a check, which nobody has trusted as it is now."""
        return self.scope == "project" and bool(self.check) and not is_trusted(self.path, home)

    def trust(self, home: Path) -> None:
        trust(self.path, home)

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "args": self.args,
            "scope": self.scope,
            "check": self.check,
        }


def parse(path: Path, scope: Scope) -> CustomCommand:
    """The command in `path`. Raises ValueError saying what's wrong with it."""
    name = path.stem.lower()
    if not NAME.match(name):
        raise ValueError(
            f"{path.name}: a command's name is lowercase letters, digits and dashes, "
            "starting with a letter"
        )
    raw = path.read_bytes()
    if len(raw) > MOST_BYTES:
        raise ValueError(f"{path.name} is over {MOST_BYTES // 1000} KB, too long for a prompt")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.name} isn't UTF-8 text") from exc
    header, body = _split(text)
    fields: dict[str, str] = {}
    for number, line in enumerate(header, start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, colon, value = line.partition(":")
        key = key.strip().lower()
        if not colon or key not in KEYS:
            raise ValueError(
                f"{path.name}, line {number}: the header takes {', '.join(sorted(KEYS))}"
            )
        fields[key] = value.strip().strip("\"'")
    body = body.strip()
    if not body:
        raise ValueError(f"{path.name} has no prompt after its header")
    rounds = DEFAULT_ROUNDS
    if "rounds" in fields:
        if not fields["rounds"].isdigit() or not 1 <= int(fields["rounds"]) <= MOST_ROUNDS:
            raise ValueError(f"{path.name}: rounds is a number from 1 to {MOST_ROUNDS}")
        rounds = int(fields["rounds"])
    description = fields.get("description") or _first_line(body)
    return CustomCommand(
        name=name,
        path=path,
        scope=scope,
        body=body,
        description=description,
        args=fields.get("args") or fields.get("argument-hint", ""),
        check=fields.get("loop", ""),
        rounds=rounds,
    )


def _split(text: str) -> tuple[list[str], str]:
    lines = text.lstrip("﻿").split("\n")
    if not lines or lines[0].strip() != "---":
        return [], text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "\n".join(lines[index + 1 :])
    return [], text  # no closing line: it's all prompt


def _first_line(body: str) -> str:
    line = body.strip().split("\n", 1)[0].lstrip("# ").strip()
    return line if len(line) <= 70 else line[:69].rstrip() + "…"


def load(
    workspace: Path | None, home: Path, reserved: Iterable[str] = ()
) -> tuple[dict[str, CustomCommand], list[str]]:
    """Your commands and the project's, by name, with the project's winning; and what's wrong
    with any file that couldn't be used. A name Zwans already has stays Zwans's."""
    taken = set(reserved) | RESERVED
    found: dict[str, CustomCommand] = {}
    problems: list[str] = []
    folders: list[tuple[Path, Scope]] = [(home / FOLDER, "user")]
    if workspace is not None:
        folders.append((workspace / ".zwans" / FOLDER, "project"))
    for folder, scope in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            try:
                command = parse(path, scope)
            except (ValueError, OSError) as exc:
                problems.append(str(exc))
                continue
            if command.name in taken:
                problems.append(f"{path.name}: /{command.name} is one of Zwans's own commands")
                continue
            found[command.name] = command
    return found, problems


def expand(command: CustomCommand, argument: str) -> str:
    """The message for /<name> <argument>: $ARGUMENTS and $1..$9 filled in, or the argument
    added after the text when the file has neither."""
    try:
        words = shlex.split(argument)
    except ValueError:
        words = argument.split()
    body = command.body
    used = "$ARGUMENTS" in body or re.search(r"\$[1-9]", body) is not None
    body = body.replace("$ARGUMENTS", argument)
    body = re.sub(r"\$([1-9])", lambda m: _word(words, int(m.group(1))), body)
    if not used and argument:
        body = f"{body}\n\n{argument}"
    return body


def _word(words: list[str], number: int) -> str:
    return words[number - 1] if number <= len(words) else ""


def loop_spec(command: CustomCommand, argument: str) -> LoopSpec:
    return LoopSpec(check=command.check, task=expand(command, argument), rounds=command.rounds)
