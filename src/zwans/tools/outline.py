"""The Outline tool: what a file or a folder defines, without the bodies.

Reading a whole file to learn its three function names spends tokens on everything else in
it, and a model that hasn't looked guesses at names. This returns the functions, classes and
types with their line numbers: enough to choose what to read next.

Python is read with its own parser, so the signatures are exact. Other languages are matched
line by line, which finds declarations written the usual way and misses unusual ones.
"""

import ast
import re
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped
from zwans.tools.refs import search_problem
from zwans.tools.text import TextFile

MAX_FILES = 60  # of a folder
MAX_PER_FILE = 14  # declarations shown for each file of a folder
MAX_LINES = 400  # of the whole answer
MAX_SIGNATURE = 110  # characters

_JS = (
    r"^\s*(export\s+)?(default\s+)?(declare\s+)?(async\s+)?function\s*\*?\s*\w+",
    r"^\s*(export\s+)?(default\s+)?(abstract\s+)?class\s+\w+",
    r"^\s*(export\s+)?(declare\s+)?(interface|type|enum)\s+\w+",
    r"^(export\s+)?(const|let|var)\s+\w+\s*(:[^=]+)?=\s*(async\s*)?(\(|function\b|<\w)",
)
PATTERNS: dict[str, tuple[str, ...]] = {
    **dict.fromkeys((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"), _JS),
    ".rs": (
        r"^\s*(pub(\([^)]*\))?\s+)?(async\s+)?(unsafe\s+)?(fn|struct|enum|trait|mod)\s+\w+",
        r"^\s*impl\b",
    ),
    ".go": (r"^func\s", r"^type\s+\w+"),
    ".java": (
        r"^\s*(public|private|protected)?\s*(static\s+)?(final\s+)?"
        r"(class|interface|enum|record)\s+\w+",
    ),
    ".rb": (r"^\s*(def|class|module)\s+\S+",),
    ".sh": (r"^\s*(function\s+)?\w+\s*\(\)",),
}
SUFFIXES = (".py", ".pyi", *PATTERNS)


class OutlineInput(BaseModel):
    path: str = Field(
        default=".",
        description="A file, or a folder for every source file in it, relative to the "
        "workspace root.",
    )


class OutlineTool:
    name = "Outline"
    description = (
        "List what a file defines, or every source file in a folder: functions, classes and "
        "types with their line numbers and signatures, without the bodies. Use it to find "
        "your way around before reading: it costs far fewer tokens than Read, and the names "
        "are the real ones. Then Read the part you need, with offset."
    )
    input_model = OutlineInput
    read_only = True

    def __init__(self, hidden: Callable[[str], Sequence[str]] | None = None) -> None:
        # The policy's globs for files a search mustn't show, as for Grep.
        self.hidden = hidden

    async def run(self, args: OutlineInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.executor.relative(args.path)
        files = await self._files(path, ctx)
        if files is None:  # one file
            found = outline(path, await _text(path, ctx))
            if not found:
                return ToolOutput(content=f"{path} defines nothing Outline recognises.")
            return ToolOutput(content="\n".join([path, *found][:MAX_LINES]))
        if not files:
            return ToolOutput(content=f"No source files in {path}.")
        lines: list[str] = []
        for file in files[:MAX_FILES]:
            try:
                found = outline(file, await _text(file, ctx))
            except (ToolError, OSError):
                continue  # binary, or gone since it was listed
            if not found:
                continue
            lines.append(file)
            lines += found[:MAX_PER_FILE]
            if len(found) > MAX_PER_FILE:
                lines.append(f"       ... {len(found) - MAX_PER_FILE} more: Outline this file")
        if len(files) > MAX_FILES:
            lines.append(f"({len(files) - MAX_FILES} more files not shown. Outline a subfolder.)")
        if len(lines) > MAX_LINES:
            lines = [*lines[:MAX_LINES], "(Cut short. Outline a subfolder or one file.)"]
        return ToolOutput(content="\n".join(lines) or f"Nothing Outline recognises in {path}.")

    async def _files(self, path: str, ctx: ToolContext) -> list[str] | None:
        """The source files under a folder, or None when `path` is a file."""
        argv = ["rg", "--files", "--no-require-git", "--path-separator", "/", "--sort", "path"]
        argv += skipped()
        for suffix in SUFFIXES:
            argv += ["--glob", f"*{suffix}"]
        for glob in self.hidden(path) if self.hidden else ():
            argv += ["--iglob", f"!{glob}"]
        result = await ctx.executor.run([*argv, path], timeout=30)
        if result.exit_code not in (0, 1):  # ripgrep exits 1 when nothing matched
            raise ToolError(search_problem("Outline", path, result.output))
        files = [line.removeprefix("./") for line in result.output.splitlines() if line]
        # ripgrep given a file lists just that file, or nothing when its suffix isn't one
        # of ours; a folder with nothing in it has no suffix of its own to speak of.
        is_file = files == [path] or (not files and bool(PurePosixPath(path).suffix))
        return None if is_file else files


async def _text(path: str, ctx: ToolContext) -> str:
    return TextFile.decode(await ctx.executor.read_bytes(path)).text


def outline(path: str, text: str) -> list[str]:
    """One line for each thing a file declares: its line number, then its signature,
    indented when it's inside a class."""
    suffix = PurePosixPath(path).suffix
    if suffix in (".py", ".pyi"):
        try:
            return _python(ast.parse(text))
        except (SyntaxError, ValueError):
            return _matched(text, (r"^\s*(async\s+)?def\s+\w+", r"^\s*class\s+\w+"))
    return _matched(text, PATTERNS.get(suffix, ()))


def _python(tree: ast.Module) -> list[str]:
    lines: list[str] = []

    def add(node: ast.stmt, depth: int) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            start = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            signature = f"{start} {node.name}({ast.unparse(node.args)}){returns}"
            lines.append(_line(node.lineno, signature, depth))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(base) for base in node.bases)
            lines.append(
                _line(node.lineno, f"class {node.name}" + (f"({bases})" if bases else ""), depth)
            )
            for child in node.body:
                add(child, depth + 1)

    for node in tree.body:
        add(node, 0)
    return lines


def _matched(text: str, patterns: Sequence[str]) -> list[str]:
    if not patterns:
        return []
    compiled = [re.compile(pattern) for pattern in patterns]
    lines = []
    for number, line in enumerate(text.splitlines(), 1):
        if any(pattern.match(line) for pattern in compiled):
            depth = (len(line) - len(line.lstrip())) // 2
            signature = line.strip().rstrip("{").rstrip()
            lines.append(_line(number, signature, min(depth, 3)))
    return lines


def _line(number: int, signature: str, depth: int) -> str:
    if len(signature) > MAX_SIGNATURE:
        signature = signature[: MAX_SIGNATURE - 3] + "..."
    return f"{number:>6}  {'  ' * depth}{signature}"
