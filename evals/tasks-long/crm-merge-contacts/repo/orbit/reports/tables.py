"""Plain-text tables for the CLI's reports."""


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100:,}.{cents % 100:02d}"


def render(headers: list[str], rows: list[list], numeric: set[int] | None = None) -> str:
    """Columns padded to their widest cell; columns in `numeric` are right-aligned."""
    numeric = numeric or set()
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in cells:
        for column, cell in enumerate(row):
            widths[column] = max(widths[column], len(cell))

    def line(row: list[str]) -> str:
        parts = [
            cell.rjust(widths[column]) if column in numeric else cell.ljust(widths[column])
            for column, cell in enumerate(row)
        ]
        return "  ".join(parts).rstrip()

    rule = "  ".join("-" * width for width in widths)
    return "\n".join([line(headers), rule, *(line(row) for row in cells)])


def counts_table(title: str, counts: dict[str, int]) -> str:
    rows = [[key or "(none)", value] for key, value in counts.items()]
    return render([title, "contacts"], rows, numeric={1})
