"""Reading unified diffs back and applying them."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field


class PatchError(ValueError):
    """The patch is malformed, or doesn't fit the file it's applied to."""


@dataclass
class Hunk:
    old_start: int  # as written in the header: 1-based, or the line before an empty range
    old_len: int
    new_start: int
    new_len: int
    lines: list[tuple[str, str]] = field(default_factory=list)  # (" " | "-" | "+", text)


_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse(text: str) -> list[Hunk]:
    """The hunks of a unified diff. File header lines (--- / +++) are skipped."""
    hunks: list[Hunk] = []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith(("--- ", "+++ ")) and not hunks:
            continue
        match = _HEADER.match(line)
        if not match:
            raise PatchError(f"expected a hunk header, got {line!r}")
        old_start, old_len, new_start, new_len = (
            int(group) if group is not None else 1 for group in match.groups()
        )
        hunk = Hunk(old_start, old_len, new_start, new_len)
        olds = news = 0
        while olds < old_len or news < new_len:
            if index >= len(lines):
                raise PatchError("the patch ends in the middle of a hunk")
            body = lines[index]
            index += 1
            kind, rest = body[:1], body[1:]
            if kind not in (" ", "-", "+"):
                raise PatchError(f"unexpected line in a hunk: {body!r}")
            hunk.lines.append((kind, rest))
            olds += kind != "+"
            news += kind != "-"
        if olds != old_len or news != new_len:
            raise PatchError("a hunk's lines don't add up to its header")
        hunks.append(hunk)
    return hunks


def apply(patch: str, old: Sequence[str]) -> list[str]:
    """The lines of `old` with the patch applied. Every kept and deleted line must match
    the file exactly where the hunk says it is."""
    out: list[str] = []
    at = 0  # the next line of old not yet copied
    for hunk in parse(patch):
        start = hunk.old_start - 1 if hunk.old_len else hunk.old_start
        if start < at or start > len(old):
            raise PatchError(f"hunk at line {hunk.old_start} is out of place")
        out.extend(old[at:start])
        at = start
        for kind, text in hunk.lines:
            if kind in (" ", "-"):
                if at >= len(old) or old[at] != text:
                    raise PatchError(f"line {at + 1} doesn't match the patch")
                at += 1
            if kind in (" ", "+"):
                out.append(text)
    out.extend(old[at:])
    return out
