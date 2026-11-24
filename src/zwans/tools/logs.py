"""The Logs tool: a long log file, grouped into the kinds of line it holds.

A log of fifty thousand lines is mostly the same few lines with different numbers in them.
This reads the whole file and groups its lines by their shape (the line with timestamps,
numbers, ids, addresses and quoted values taken out), so each kind of line shows once with
how many times it came and where. Errors and warnings come first; a Python traceback is
kept whole, as one entry, under its exception. A pattern narrows it to matching lines.
"""

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_BYTES = 50_000_000  # the end of a bigger log is read
MAX_GROUPS = 40  # kinds of ordinary line listed
MAX_PROBLEMS = 30  # kinds of error or warning listed
MAX_EXAMPLE = 300  # characters of each example line
MAX_TRACEBACK_LINES = 30

TIMESTAMP = re.compile(
    r"^\s*\[?(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\w{3} [ \d]\d \d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]?\s*"
)
SHAPES = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"\"[^\"]*\"|'[^']*'"), "<str>"),
    (re.compile(r"(?<![A-Za-z])-?\d+(?:\.\d+)?(?:ms|s|kb|mb|gb|%)?(?![A-Za-z])", re.I), "<n>"),
]
PROBLEM = re.compile(
    r"\b(?:error|err|fatal|critical|panic|exception|fail(?:ed|ure)?|warn(?:ing)?)\b", re.I
)
WARNING = re.compile(r"\bwarn(?:ing)?\b", re.I)


class LogsInput(BaseModel):
    path: str = Field(description="The log file, relative to the workspace root.")
    pattern: str = Field(
        default="", description="A regular expression: only lines matching it are grouped."
    )


@dataclass
class Group:
    example: str
    first: int
    last: int
    count: int = 0
    level: int = 0  # 2 for an error, 1 for a warning, 0 otherwise
    lines: list[str] = field(default_factory=list)  # a traceback's, whole


class LogsTool:
    name = "Logs"
    description = (
        "Read a long log file as the kinds of line it holds: lines that differ only in "
        "times, numbers, ids or quoted values are grouped, each shown once with its count "
        "and where it first and last came. Errors and warnings come first, and Python "
        "tracebacks are kept whole. Use it instead of Read for a log too long to read."
    )
    input_model = LogsInput
    read_only = True

    async def run(self, args: LogsInput, ctx: ToolContext) -> ToolOutput:
        data = await ctx.executor.read_bytes(args.path)
        cut = len(data) > MAX_BYTES
        text = data[-MAX_BYTES:].decode("utf-8", "replace")
        try:
            only = re.compile(args.pattern) if args.pattern else None
        except re.error as exc:
            raise ToolError(f"pattern isn't a valid regular expression: {exc}") from exc
        lines = text.splitlines()
        if cut:
            lines = lines[1:]  # the first may be part of one
        groups, matched = group_lines(lines, only)
        return ToolOutput(content=_report(args.path, groups, len(lines), matched, only, cut))


def shape(line: str) -> str:
    """The line with what varies taken out."""
    bare = TIMESTAMP.sub("", line, count=1)
    for pattern, mark in SHAPES:
        bare = pattern.sub(mark, bare)
    return " ".join(bare.split())


def group_lines(lines: list[str], only: re.Pattern[str] | None) -> tuple[list[Group], int]:
    groups: dict[str, Group] = {}
    matched = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        number = index + 1
        block = [line]
        if line.lstrip().startswith("Traceback (most recent call last)"):
            index += 1
            while index < len(lines) and (
                lines[index].startswith((" ", "\t")) or not lines[index].strip()
            ):
                block.append(lines[index])
                index += 1
            if index < len(lines):
                block.append(lines[index])  # the exception itself
            key_line = block[-1]
        else:
            key_line = line
        index += 1
        if not line.strip() or (only and not any(only.search(each) for each in block)):
            continue
        matched += 1
        key = ("traceback: " if len(block) > 1 else "") + shape(key_line)
        group = groups.get(key)
        if group is None:
            level = 2 if len(block) > 1 else _level(key_line)
            group = groups[key] = Group(key_line.strip(), number, number, level=level)
            if len(block) > 1:
                group.lines = block[:MAX_TRACEBACK_LINES]
        group.count += 1
        group.last = number
    return list(groups.values()), matched


def _level(line: str) -> int:
    if not PROBLEM.search(line):
        return 0
    return 1 if WARNING.search(line) else 2


def _report(
    path: str,
    groups: list[Group],
    total: int,
    matched: int,
    only: re.Pattern[str] | None,
    cut: bool,
) -> str:
    if not groups:
        return f"{path}: {total:,} lines, none of them matching." if only else f"{path} is empty."
    head = f"{path}: {total:,} lines"
    if only:
        head += f", {matched:,} matching {only.pattern!r}"
    head += f", of {len(groups):,} kinds."
    if cut:
        head += f" (Only the last {MAX_BYTES // 1_000_000} MB were read.)"
    problems = sorted((g for g in groups if g.level), key=lambda g: (-g.level, g.first))
    ordinary = sorted((g for g in groups if not g.level), key=lambda g: -g.count)
    parts = [head]
    if problems:
        parts += ["", f"Errors and warnings ({len(problems)} kinds, first seen first):"]
        parts += [_entry(g) for g in problems[:MAX_PROBLEMS]]
        if len(problems) > MAX_PROBLEMS:
            parts.append(f"... and {len(problems) - MAX_PROBLEMS} more kinds")
    if ordinary:
        parts += ["", f"Other lines ({len(ordinary)} kinds, most frequent first):"]
        parts += [_entry(g) for g in ordinary[:MAX_GROUPS]]
        if len(ordinary) > MAX_GROUPS:
            rest = sum(g.count for g in ordinary[MAX_GROUPS:])
            parts.append(f"... and {len(ordinary) - MAX_GROUPS} more kinds ({rest:,} lines)")
    return "\n".join(parts)


def _entry(group: Group) -> str:
    where = f"line {group.first:,}" if group.count == 1 else f"lines {group.first:,}-{group.last:,}"
    label = {2: "ERROR ", 1: "WARN  "}.get(group.level, "")
    times = f"{group.count:>7,}x"
    example = group.example
    if len(example) > MAX_EXAMPLE:
        example = example[:MAX_EXAMPLE] + "…"
    entry = f"{times} {label}{example}  ({where})"
    if group.lines:
        body = "\n".join(f"          {line.rstrip()}" for line in group.lines)
        entry += f"\n{body}"
    return entry
