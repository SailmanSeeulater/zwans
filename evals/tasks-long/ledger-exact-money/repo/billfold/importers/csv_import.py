"""Importing the CSV files banks let you download.

Every bank lays these out differently, so a CsvProfile says which column is which. The
amount is either one signed column or a debit and a credit column. Amounts may be written
"1,234.50", "-12.00", "(12.00)" (negative), "12.00-" (negative, as some banks print
them) or with a currency sign; with `decimal_comma` "1.234,50" means 1234.50.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..dates import parse_date
from ..errors import ImportProblem, ValidationError
from .base import ImportedRow, ImportResult, commit_rows

if TYPE_CHECKING:
    from ..book import Book

_STRIP = re.compile(r"[^\d.,()+\-]")


@dataclass
class CsvProfile:
    date: str = "date"
    amount: str | None = "amount"
    debit: str | None = None
    credit: str | None = None
    payee: str = "payee"
    memo: str | None = "memo"
    category: str | None = None
    ref: str | None = None
    date_format: str | None = None
    decimal_comma: bool = False
    delimiter: str = ","
    skip_lines: int = 0
    negate: bool = False
    encoding: str = "utf-8-sig"
    extra: dict[str, str] = field(default_factory=dict)

    def needed(self) -> list[str]:
        columns = [self.date, self.payee]
        if self.amount:
            columns.append(self.amount)
        else:
            columns += [c for c in (self.debit, self.credit) if c]
        return columns


PROFILES = {
    "default": CsvProfile(),
    "debit-credit": CsvProfile(amount=None, debit="debit", credit="credit"),
    "eu-bank": CsvProfile(
        date="Buchungstag", amount="Betrag", payee="Empfaenger", memo="Verwendungszweck",
        date_format="%d.%m.%Y", decimal_comma=True, delimiter=";",
    ),
}


def _number(text: str, decimal_comma: bool) -> float:
    """A bank's way of writing an amount, as a number. Empty means zero."""
    raw = text.strip()
    if not raw:
        return 0.0
    cleaned = _STRIP.sub("", raw)
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative, cleaned = True, cleaned[1:-1]
    if cleaned.endswith("-"):
        negative, cleaned = not negative, cleaned[:-1]
    if cleaned.startswith("-"):
        negative, cleaned = not negative, cleaned[1:]
    elif cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if decimal_comma:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"not an amount: {raw!r}") from None
    return -value if negative else value


def read_rows(text: str, profile: CsvProfile) -> list[ImportedRow]:
    lines = text.splitlines()[profile.skip_lines:]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=profile.delimiter)
    header = [name.strip() for name in (reader.fieldnames or [])]
    reader.fieldnames = header
    missing = [column for column in profile.needed() if column not in header]
    if missing:
        raise ImportProblem(f"the file has no column {', '.join(missing)}")
    rows = []
    for number, record in enumerate(reader, start=profile.skip_lines + 2):
        if not any((value or "").strip() for value in record.values()):
            continue
        try:
            day = parse_date(record[profile.date], profile.date_format)
            if profile.amount:
                amount = _number(record[profile.amount] or "", profile.decimal_comma)
            else:
                credit = _number(record.get(profile.credit or "", "") or "", profile.decimal_comma)
                debit = _number(record.get(profile.debit or "", "") or "", profile.decimal_comma)
                amount = credit - abs(debit)
        except (ValueError, ValidationError) as error:
            raise ImportProblem(str(error), number) from None
        if profile.negate:
            amount = -amount
        rows.append(ImportedRow(
            date=day,
            amount=amount,
            payee=(record.get(profile.payee) or "").strip(),
            memo=(record.get(profile.memo or "") or "").strip(),
            category=(record.get(profile.category or "") or "").strip() or None,
            ref=(record.get(profile.ref or "") or "").strip() or None,
            line=number,
        ))
    return rows


def import_csv(
    book: Book,
    account: str,
    path: Path | str,
    profile: CsvProfile | str = "default",
    *,
    dry_run: bool = False,
) -> ImportResult:
    if isinstance(profile, str):
        try:
            profile = PROFILES[profile]
        except KeyError:
            raise ImportProblem(f"no CSV profile called {profile!r}") from None
    path = Path(path)
    try:
        text = path.read_text(profile.encoding)
    except (OSError, UnicodeDecodeError) as error:
        raise ImportProblem(f"can't read {path}: {error}") from None
    rows = read_rows(text, profile)
    return commit_rows(book, account, rows, path.name, dry_run=dry_run)
