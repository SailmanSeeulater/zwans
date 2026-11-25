"""Small text helpers shared by the CLI, the reports and the mail code."""

from __future__ import annotations

import re
import textwrap

_SLUG = re.compile(r"[^a-z0-9]+")
_HANDLE = re.compile(r"^[a-z][a-z0-9_.-]{1,31}$")


def slugify(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")


def is_handle(text: str) -> bool:
    return bool(_HANDLE.match(text))


def truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(width - 1, 0)] + "…"


def wrap(text: str, width: int = 72, indent: str = "") -> str:
    paragraphs = [p for p in text.split("\n\n")]
    out = []
    for paragraph in paragraphs:
        lines = paragraph.splitlines() or [""]
        joined = " ".join(line.strip() for line in lines)
        out.append(
            textwrap.fill(joined, width=width, initial_indent=indent, subsequent_indent=indent)
            if joined
            else indent
        )
    return "\n\n".join(out)


def table(headers: list[str], rows: list[list[str]]) -> str:
    """A plain fixed-width table, as the CLI and the text reports print them."""
    cells = [[str(h) for h in headers]] + [[str(c) for c in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = []
    for n, row in enumerate(cells):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def parse_tags(text: str) -> list[str]:
    tags = []
    for part in re.split(r"[,\s]+", text):
        part = part.strip().lower()
        if part and part not in tags:
            tags.append(part)
    return tags
