"""Shows file changes in the terminal as coloured diff lines: what an Edit or Write will do,
before the user allows it, and what it did, after it ran."""

import difflib
from typing import Any

import typer

MAX_LINES = 40  # longer changes are cut, with a note of how much is left out
INDENT = "    "


def show_diff(diff: str, limit: int = MAX_LINES) -> None:
    """A unified diff without its file headers (the call line already names the file)."""
    lines = [line for line in diff.splitlines() if not line.startswith(("--- ", "+++ "))]
    _show(lines, limit)


def show_change(tool: str, args: dict[str, Any]) -> None:
    """What a call is about to change, so the user doesn't approve it blind."""
    if tool == "Edit":
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
                typer.secho(f"{INDENT}{line}", dim=True)
            if len(lines) > MAX_LINES:
                typer.secho(f"{INDENT}... {_count(len(lines) - MAX_LINES, 'more line')}", dim=True)


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
        typer.secho(f"{INDENT}{line}", **_style(line))
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
