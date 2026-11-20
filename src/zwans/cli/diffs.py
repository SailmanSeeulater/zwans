"""Shows file changes in the terminal as coloured diff lines: what an Edit or Write will do,
before the user allows it, and what it did, after it ran."""

import difflib
from typing import Any

import typer

from zwans.cli.terminal_text import printable

MAX_LINES = 40  # longer changes are cut, with a note of how much is left out
INDENT = "    "


def show_diff(diff: str, limit: int = MAX_LINES) -> None:
    """A unified diff without its file headers (the call line already names the file)."""
    _show(_body(diff), limit)


def show_change(tool: str, args: dict[str, Any], preview: str | None = None) -> None:
    """What a call is about to change, so the user doesn't approve it blind. `preview` is the
    diff against the file as it is now, when the loop could work it out."""
    if preview is not None and tool in ("Edit", "Write"):
        show_preview(tool, preview)
    elif tool == "Edit":
        _show(edit_lines(args), MAX_LINES)
    elif tool == "Write" and isinstance(args.get("content"), str):
        lines = args["content"].splitlines()
        if not lines:
            typer.secho(f"{INDENT}The new contents are empty.", dim=True)
            return
        typer.secho(f"{INDENT}New contents ({_count(len(lines), 'line')}):", dim=True)
        _show([f"+{line}" for line in lines], MAX_LINES)
    elif tool == "Bash" and isinstance(args.get("command"), str):
        command = args["command"].strip()
        lines = command.splitlines()
        # The call line shows only the start of a long or multi-line command.
        if len(lines) > 1 or len(command) > 100:
            for line in lines[:MAX_LINES]:
                typer.secho(f"{INDENT}{printable(line)}", dim=True)
            if len(lines) > MAX_LINES:
                typer.secho(f"{INDENT}... {_count(len(lines) - MAX_LINES, 'more line')}", dim=True)


def show_preview(tool: str, preview: str) -> None:
    """A file tool's diff, after a line saying whether a Write makes a new file or replaces
    one, and how much of it."""
    if tool == "Write":
        typer.secho(f"{INDENT}{describe_write(preview)}", dim=True)
    _show(_body(preview), MAX_LINES)


def describe_write(preview: str) -> str:
    """ "New file (3 lines):", or what replacing the existing file changes."""
    lines = _body(preview)
    added = sum(line.startswith("+") for line in lines)
    removed = sum(line.startswith("-") for line in lines)
    if preview.startswith("--- /dev/null"):
        return f"New file ({_count(added, 'line')}):" if added else "New file, empty."
    if not lines:
        return "Replaces the existing file with the same contents."
    if not added and not removed:  # the diff was too large to show
        return "Replaces the existing file:"
    return (
        f"Replaces the existing file: {_count(removed, 'line')} removed, "
        f"{_count(added, 'line')} added:"
    )


def _body(diff: str) -> list[str]:
    """A unified diff's lines without its file headers."""
    return [line for line in diff.splitlines() if not line.startswith(("--- ", "+++ "))]


def edit_lines(args: dict[str, Any]) -> list[str]:
    """An Edit's old and new text as diff lines. The hunk headers are left out, since their
    line numbers would count from the start of old_string, not the file."""
    old, new = args.get("old_string"), args.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return []
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="")
    lines: list[str] = []
    for line in diff:
        if line.startswith(("--- ", "+++ ")):
            continue
        if line.startswith("@@"):
            if lines:
                lines.append("...")
            continue
        lines.append(line)
    if args.get("replace_all") is True:
        lines.append("(every occurrence)")
    return lines


def _show(lines: list[str], limit: int) -> None:
    for line in lines[:limit]:
        typer.secho(f"{INDENT}{printable(line)}", **_style(line))
    if len(lines) > limit:
        typer.secho(f"{INDENT}... {_count(len(lines) - limit, 'more line')}", dim=True)


def _style(line: str) -> dict[str, Any]:
    if line.startswith("+"):
        return {"fg": "green"}
    if line.startswith("-"):
        return {"fg": "red"}
    if line.startswith("@@"):
        return {"fg": "cyan", "dim": True}
    return {"dim": True}


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
