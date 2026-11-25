"""Plain-text and CSV tables for the reports."""

import csv
import io
from collections.abc import Sequence

Cell = str | int


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Cell]], *, numeric: set[int] | None = None) -> str:
    """A fixed-width table. Columns listed in `numeric` (by index) are right-aligned."""
    numeric = numeric or set()
    text_rows = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in text_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells: Sequence[str]) -> str:
        parts = [
            cell.rjust(widths[i]) if i in numeric else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "  ".join(parts).rstrip()

    out = [line(list(headers)), line(["-" * w for w in widths])]
    out.extend(line(row) for row in text_rows)
    return "\n".join(out) + "\n"


def render_csv(headers: Sequence[str], rows: Sequence[Sequence[Cell]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()
