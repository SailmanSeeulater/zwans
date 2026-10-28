"""Reading the desks' CSV exports and writing CSV reports."""

import csv
import io
from collections.abc import Iterable, Iterator
from pathlib import Path

REQUIRED_COLUMNS = ("event", "loan_no", "member", "barcode", "title", "at")
OPTIONAL_COLUMNS = ("branch",)


class ExportError(Exception):
    pass


def normalise_header(name: str) -> str:
    """'Loan No' / 'loan-no' / ' LOAN_NO ' -> 'loan_no'."""
    return "_".join(name.strip().lower().replace("-", " ").split())


def read_rows(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    """Rows of an export as dicts keyed by normalised column names. Old exports have
    no branch column; their rows get an empty branch."""
    reader = csv.reader(lines)
    try:
        header = [normalise_header(name) for name in next(reader)]
    except StopIteration:
        return
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise ExportError(f"the export has no {', '.join(missing)} column")
    for values in reader:
        if not any(value.strip() for value in values):
            continue  # blank line
        if len(values) != len(header):
            values = (values + [""] * len(header))[: len(header)]
        row = dict(zip(header, (value.strip() for value in values), strict=True))
        row.setdefault("branch", "")
        yield row


def read_export(path: Path) -> list[dict[str, str]]:
    # utf-8-sig: the Hillside desk writes a byte order mark.
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(read_rows(handle))


def to_csv(header: list[str], rows: Iterable[Iterable[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()
