"""What to tell a model whose tool call couldn't run, so its next try can be right.

Two mistakes are common, most of all with small models: arguments that don't fit the tool
(a line offset of 0, a command given to Write), and paths guessed rather than looked up. The
error for each says what the tool takes or where the file may be, instead of only what went
wrong.
"""

import difflib
import errno
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from zwans.tools.base import Tool, ToolContext

SKIPPED_FOLDERS = {"node_modules", "__pycache__", "venv", "dist", "build", "target"}
MAX_FILES = 5000  # looked through for a file of the same name
MAX_LISTED = 20  # entries of a folder shown
MAX_SUGGESTED = 3


def invalid_input(
    tool: Tool[Any], given: object, error: ValidationError, tools: Mapping[str, Tool[Any]]
) -> str:
    """Why `given` isn't input for `tool`, what the tool does take, and which other tool the
    input fits, if one does."""
    fields = tool.input_model.model_fields
    problems = []
    for found in error.errors():
        where = ".".join(str(part) for part in found["loc"]) or "the input"
        if found["type"] == "missing":
            problems.append(f"{where} is required")
        else:
            problems.append(f"{where}: {found['msg']}")
    keys = list(given) if isinstance(given, dict) else []
    unknown = [key for key in keys if key not in fields]
    if unknown:
        isnt = "isn't a parameter" if len(unknown) == 1 else "aren't parameters"
        problems.append(f"{', '.join(unknown)} {isnt}")
    takes = ", ".join(
        name if field.is_required() else f"{name} (optional)" for name, field in fields.items()
    )
    message = f"Invalid input for {tool.name}: {'; '.join(problems)}. {tool.name} takes {takes}."
    for other in tools.values():
        if other is not tool and keys and _fits(keys, other):
            message += f" That input fits {other.name}: call {other.name} instead."
            break
    return message


def _fits(keys: list[str], tool: Tool[Any]) -> bool:
    fields = tool.input_model.model_fields
    required = {name for name, field in fields.items() if field.is_required()}
    return set(keys) <= set(fields) and required <= set(keys)


def missing_path(root: Path, missing: Path) -> str:
    """Where a file that isn't at `missing` may be: files of the same or a similar name in
    the workspace, or else what the nearest folder that exists holds. "" when it can't say."""
    try:
        missing.relative_to(root)
    except ValueError:
        return ""
    if not root.is_dir():
        return ""
    files = _files(root)
    same = _named(files, missing.name)
    if same:
        return f"A file called {missing.name} is at {_join(same[:MAX_SUGGESTED])}."
    by_name: dict[str, str] = {}
    for path in files:
        by_name.setdefault(Path(path).name, path)
    close = difflib.get_close_matches(missing.name, list(by_name), n=MAX_SUGGESTED, cutoff=0.6)
    if close:
        return f"Did you mean {_join([by_name[name] for name in close])}?"
    folder = missing.parent
    while folder != root and not folder.is_dir():
        folder = folder.parent
    try:
        entries = sorted(
            entry.name + ("/" if entry.is_dir() else "")
            for entry in folder.iterdir()
            if not entry.name.startswith(".")
        )
    except OSError:
        return ""
    where = "The workspace root" if folder == root else f"{folder.relative_to(root).as_posix()}/"
    if not entries:
        return f"{where} is empty."
    more = f", and {len(entries) - MAX_LISTED} more" if len(entries) > MAX_LISTED else ""
    return f"{where} holds: {', '.join(entries[:MAX_LISTED])}{more}."


def only_file_named(ctx: ToolContext, path: str) -> str | None:
    """The workspace path of the one file named like `path`, which isn't there, when exactly
    one file of that name exists; None otherwise."""
    root = workspace_root(ctx)
    if root is None or not root.is_dir():
        return None
    try:
        missing = root / ctx.executor.relative(path)
    except OSError:
        return None
    if missing.exists():
        return None
    same = _named(_files(root), missing.name)
    return same[0] if len(same) == 1 else None


def _named(files: list[str], name: str) -> list[str]:
    return [path for path in files if Path(path).name == name]


def _files(root: Path) -> list[str]:
    """Paths of the workspace's files, relative to it, leaving out hidden and dependency
    folders, and stopping at MAX_FILES."""
    found: list[str] = []
    for folder, folders, names in os.walk(root):
        folders[:] = sorted(
            f for f in folders if not f.startswith(".") and f not in SKIPPED_FOLDERS
        )
        for name in sorted(names):
            found.append((Path(folder) / name).relative_to(root).as_posix())
            if len(found) >= MAX_FILES:
                return found
    return found


def _join(paths: list[str]) -> str:
    return paths[0] if len(paths) == 1 else ", ".join(paths[:-1]) + " or " + paths[-1]


def workspace_root(ctx: ToolContext) -> Path | None:
    """The workspace folder, for executors that have one on this machine."""
    root = getattr(ctx.executor, "root", None)
    return Path(root) if root is not None else None


def raise_if_missing(ctx: ToolContext, path: str, output: str) -> None:
    """After a search command failed: if that's because `path` isn't there, raise the
    FileNotFoundError a read of it would have, so the model is told where to look instead."""
    root = workspace_root(ctx)
    if root is None or "No such file or directory" not in output:
        return
    try:
        missing = root / ctx.executor.relative(path)
    except OSError:
        return
    if not missing.exists():
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(missing))
