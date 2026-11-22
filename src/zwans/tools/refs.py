"""References and Rename: find a name wherever it's used, and change it everywhere at once.

These work on names, not on meaning. A language server knows that `total` in one file is
the function and in another is an unrelated variable; this doesn't, and treats every
identifier spelled that way as the same. What it does know is what an identifier is: in
Python, where the file is read token by token, a name inside a string or a comment is left
alone. In other languages a whole-word match is used, which can't tell.

That is the honest trade for needing nothing installed. It is right for the common case, a
name that means one thing in the project, and the diff shows every place before anything
is written.
"""

import io
import re
import shutil
import subprocess
import tokenize
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped
from zwans.tools.text import TextFile, unified_diff

IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
MAX_SHOWN = 200  # references listed
MAX_FILES = 300  # files one Rename may change
SCAN_TIMEOUT = 20  # seconds to find the files that mention a name


class ReferencesInput(BaseModel):
    symbol: str = Field(description="The name to look for: a function, class, variable or type.")
    path: str = Field(default=".", description="Folder or file to look in, relative to the root.")


class RenameInput(BaseModel):
    old: str = Field(description="The name as it is now.")
    new: str = Field(description="The name to give it.")
    path: str = Field(default=".", description="Folder or file to rename in, relative to the root.")


class ReferencesTool:
    name = "References"
    description = (
        "List every place a name is used: each file, line and the line's text. It matches "
        "the identifier exactly, so `total` doesn't find `subtotal`, and in Python it skips "
        "strings and comments. Use it before changing a function, to see what calls it."
    )
    input_model = ReferencesInput
    read_only = True

    async def run(self, args: ReferencesInput, ctx: ToolContext) -> ToolOutput:
        symbol = _identifier(args.symbol)
        found: list[str] = []
        for file in await _mentioning(symbol, ctx.executor.search_path(args.path), ctx):
            try:
                text = TextFile.decode(await ctx.executor.read_bytes(file)).text
            except (ToolError, OSError):
                continue
            lines = text.splitlines()
            for row in sorted({row for row, _ in positions(file, text, symbol)}):
                found.append(f"{file}:{row}: {lines[row - 1].strip()[:200]}")
        if not found:
            return ToolOutput(content=f"No uses of {symbol} found.")
        shown = found[:MAX_SHOWN]
        if len(found) > MAX_SHOWN:
            shown.append(f"({len(found) - MAX_SHOWN} more not shown. Narrow it with path.)")
        return ToolOutput(content="\n".join(shown))


class RenameTool:
    name = "Rename"
    description = (
        "Rename an identifier everywhere it is used, in every file under a path, in one "
        "call. It changes whole names only, and in Python leaves strings and comments alone. "
        "It goes by the name, not by meaning: if two different things share the name, both "
        "are renamed, so check with References first when the name is a common one."
    )
    input_model = RenameInput
    read_only = False

    def __init__(self, root: Path) -> None:
        self.root = root

    def edited_paths(self, args: dict[str, Any]) -> list[str]:
        """The files a call would change, from its raw input, for the policy to judge each
        one as an edit. Found on this machine's copy of the workspace, which every executor
        shares."""
        old, path = args.get("old"), args.get("path", ".")
        if not isinstance(old, str) or not IDENTIFIER.match(old) or not isinstance(path, str):
            return []
        return _mentioning_now(old, self.root, path)

    async def run(self, args: RenameInput, ctx: ToolContext) -> ToolOutput:
        changed = await self._plan(args, ctx)
        for file, (source, updated, _) in changed.items():
            await ctx.executor.write_bytes(file, source.encode(updated))
        places = sum(count for _, _, count in changed.values())
        per_file = ", ".join(f"{file} ({count})" for file, (_, _, count) in changed.items())
        files = "1 file" if len(changed) == 1 else f"{len(changed)} files"
        return ToolOutput(
            content=f"Renamed {args.old} to {args.new} in {places} "
            f"{'place' if places == 1 else 'places'} across {files}: {per_file}.",
            diff=_diff(changed),
        )

    async def preview(self, args: RenameInput, ctx: ToolContext) -> str:
        return _diff(await self._plan(args, ctx))

    async def _plan(
        self, args: RenameInput, ctx: ToolContext
    ) -> dict[str, tuple[TextFile, str, int]]:
        """Each file that changes: as it is, as it would be, and how many places differ."""
        old, new = _identifier(args.old), _identifier(args.new)
        if old == new:
            raise ToolError("old and new are the same name, so there is nothing to do.")
        changed: dict[str, tuple[TextFile, str, int]] = {}
        for file in await _mentioning(old, ctx.executor.relative(args.path), ctx):
            try:
                source = TextFile.decode(await ctx.executor.read_bytes(file))
            except (ToolError, OSError):
                continue
            found = positions(file, source.text, old)
            if found:
                changed[file] = (source, _replaced(source.text, found, len(old), new), len(found))
        if not changed:
            raise ToolError(f"No uses of {old} found under {args.path}, so nothing was renamed.")
        if len(changed) > MAX_FILES:
            raise ToolError(
                f"{old} is used in {len(changed)} files, more than Rename changes at once "
                f"({MAX_FILES}). Narrow it with path."
            )
        return changed


def positions(path: str, text: str, symbol: str) -> list[tuple[int, int]]:
    """Where `symbol` appears as an identifier: (line, column) pairs, lines from 1. Python
    is read token by token, so strings and comments don't count; anything else is matched
    as a whole word."""
    if PurePosixPath(path).suffix in (".py", ".pyi"):
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            return [t.start for t in tokens if t.type == tokenize.NAME and t.string == symbol]
        except (tokenize.TokenError, SyntaxError, ValueError):
            pass  # not valid Python as it stands: fall back to whole words
    word = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
    return [
        (row, match.start())
        for row, line in enumerate(text.split("\n"), 1)
        for match in word.finditer(line)
    ]


def _replaced(text: str, found: Sequence[tuple[int, int]], width: int, new: str) -> str:
    lines = text.split("\n")
    for row, column in sorted(found, reverse=True):  # from the end, so columns stay true
        line = lines[row - 1]
        lines[row - 1] = line[:column] + new + line[column + width :]
    return "\n".join(lines)


def _identifier(name: str) -> str:
    name = name.strip()
    if not IDENTIFIER.match(name):
        raise ToolError(f"{name!r} isn't an identifier: use letters, digits and underscores.")
    return name


def _scan_argv(symbol: str, path: str) -> list[str]:
    argv = ["rg", "--files-with-matches", "--fixed-strings", "--word-regexp", "--no-require-git"]
    return [*argv, "--path-separator", "/", "--sort", "path", *skipped(), "--", symbol, path]


async def _mentioning(symbol: str, path: str, ctx: ToolContext) -> list[str]:
    """The files under `path` that mention `symbol` as a word."""
    result = await ctx.executor.run(_scan_argv(symbol, path), timeout=SCAN_TIMEOUT)
    if result.exit_code not in (0, 1):  # ripgrep exits 1 when nothing matched
        raise ToolError(search_problem("The search", path, result.output))
    return [line.removeprefix("./") for line in result.output.splitlines() if line]


def search_problem(who: str, path: str, output: str) -> str:
    """Why ripgrep couldn't look in `path`, for the model: most often a path that isn't
    there, which it should hear plainly rather than as ripgrep's own words."""
    if "No such file or directory" in output:
        return (
            f'There\'s no file or folder called {path!r} in the workspace. Use "." for the '
            "whole workspace, or Glob to find the path."
        )
    return f"{who} couldn't look in {path}: {output.strip()}"


def _mentioning_now(symbol: str, root: Path, path: str) -> list[str]:
    """The same list, found without waiting, for the policy's check."""
    ripgrep = shutil.which("rg")
    if ripgrep is None:
        return []
    try:
        result = subprocess.run(
            [ripgrep, *_scan_argv(symbol, path)[1:]],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=SCAN_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.removeprefix("./") for line in result.stdout.splitlines() if line]


def _diff(changed: dict[str, tuple[TextFile, str, int]]) -> str:
    return "".join(
        unified_diff(file, source.text, updated) for file, (source, updated, _) in changed.items()
    )
