"""Plain-text tables for reports and the CLI."""

from __future__ import annotations

from collections.abc import Sequence


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    align: str | None = None,
    footer: Sequence[object] | None = None,
) -> str:
    """Columns padded to fit; align is one letter per column, 'l' or 'r'."""
    align = align or "l" * len(headers)
    body = [[str(cell) for cell in row] for row in rows]
    foot = [str(cell) for cell in footer] if footer else None
    widths = [len(h) for h in headers]
    for row in body + ([foot] if foot else []):
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: Sequence[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            if align[index] == "r":
                parts.append(cell.rjust(widths[index]))
            else:
                parts.append(cell.ljust(widths[index]))
        return "  ".join(parts).rstrip()

    out = [line(headers), line(["-" * w for w in widths])]
    out.extend(line(row) for row in body)
    if foot:
        out.append(line(["-" * w for w in widths]))
        out.append(line(foot))
    return "\n".join(out)


def heading(text: str) -> str:
    return f"{text}\n{'=' * len(text)}"
