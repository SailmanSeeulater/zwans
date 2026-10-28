"""Plain-text tables for the desk printouts."""

from collections.abc import Sequence


def table(
    header: Sequence[str], rows: Sequence[Sequence[str]], right: set[int] | None = None
) -> list[str]:
    """Lines of a table with a header and a rule, columns padded to fit.
    Columns whose index is in `right` are right-aligned."""
    right = right or set()
    widths = [len(name) for name in header]
    for row in rows:
        if len(row) != len(header):
            raise ValueError("every row needs one value per column")
        widths = [max(width, len(value)) for width, value in zip(widths, row, strict=True)]

    def line(values: Sequence[str]) -> str:
        cells = [
            value.rjust(width) if index in right else value.ljust(width)
            for index, (value, width) in enumerate(zip(values, widths, strict=True))
        ]
        return "  ".join(cells).rstrip()

    return [line(header), line(["-" * width for width in widths])] + [line(row) for row in rows]


def indent(lines: Sequence[str], by: int = 2) -> list[str]:
    return [(" " * by + line) if line else line for line in lines]
