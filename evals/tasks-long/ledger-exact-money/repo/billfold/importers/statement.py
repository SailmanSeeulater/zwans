"""Importing bank statements in the plain-text format our bank's export tool writes.

    STATEMENT
    ACCOUNT DE89 3704 0044 0532 0130 00
    CURRENCY EUR
    FROM 2026-03-01 TO 2026-03-31
    OPENING 1.234,50
    2026-03-02;-45,10;REWE Markt;Card payment 1234
    2026-03-05;2.500,00;ACME GmbH;Salary March
    2026-03-07;(12,00);Bank;Account fee
    CLOSING 3.677,40

Amounts use a decimal comma and dots between thousands; a negative amount may be written
in parentheses. The entries must add up from the opening to the closing balance, and the
opening balance must match what the account held the day before the statement starts
(unless the account has nothing before then).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..currencies import normalise_code
from ..errors import ImportProblem, StatementMismatch, UnknownCurrency
from .base import ImportedRow, ImportResult, commit_rows

if TYPE_CHECKING:
    from ..book import Book

_AMOUNT = re.compile(r"^\(?-?[\d.]+(,\d+)?\)?$")


@dataclass
class Statement:
    account_ref: str = ""
    currency: str = "EUR"
    start: date | None = None
    end: date | None = None
    opening: float = 0.0
    closing: float | None = None
    entries: list[ImportedRow] = field(default_factory=list)

    @property
    def movement(self) -> float:
        return sum(entry.amount for entry in self.entries)


def euro_number(text: str) -> float:
    text = text.strip().replace(" ", "")
    if not _AMOUNT.match(text):
        raise ValueError(f"not an amount: {text!r}")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    value = float(text.replace(".", "").replace(",", "."))
    return -value if negative else value


def parse_statement(text: str) -> Statement:
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines or lines[0].strip() != "STATEMENT":
        raise ImportProblem("not a bank statement (first line should be STATEMENT)", 1)
    statement = Statement()
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        keyword, _, rest = line.partition(" ")
        try:
            if keyword == "ACCOUNT":
                statement.account_ref = rest.strip()
            elif keyword == "CURRENCY":
                statement.currency = normalise_code(rest.strip())
            elif keyword == "FROM":
                first, _, last = rest.partition(" TO ")
                statement.start = date.fromisoformat(first.strip())
                statement.end = date.fromisoformat(last.strip())
            elif keyword == "OPENING":
                statement.opening = euro_number(rest)
            elif keyword == "CLOSING":
                statement.closing = euro_number(rest)
            else:
                statement.entries.append(_entry(line, number, statement))
        except (ValueError, UnknownCurrency) as error:
            raise ImportProblem(str(error), number) from None
    if statement.closing is None:
        raise ImportProblem("statement has no CLOSING line")
    return statement


def _entry(line: str, number: int, statement: Statement) -> ImportedRow:
    parts = line.split(";")
    if len(parts) < 3:
        raise ValueError(f"can't read entry {line!r}")
    day = date.fromisoformat(parts[0].strip())
    if statement.start and statement.end and not statement.start <= day <= statement.end:
        raise ValueError(f"{day} is outside the statement period")
    index = len(statement.entries) + 1
    ref = f"stmt:{statement.account_ref.replace(' ', '')}:{day.isoformat()}:{index}"
    return ImportedRow(
        date=day,
        amount=euro_number(parts[1]),
        payee=parts[2].strip(),
        memo=";".join(parts[3:]).strip(),
        ref=ref,
        line=number,
    )


def check_totals(statement: Statement) -> None:
    expected = statement.opening + statement.movement
    if abs(expected - statement.closing) > 0.005:
        raise StatementMismatch(
            f"entries add up to {expected:.2f} but the statement closes at {statement.closing:.2f}"
        )


def check_opening(book: Book, account: str, statement: Statement) -> None:
    acct = book.account(account)
    if statement.start is None:
        return
    before = book.transactions_for(acct, end=statement.start - timedelta(days=1))
    if not before:
        return
    held = book.balance(acct, statement.start - timedelta(days=1))
    if abs(held - statement.opening) > 0.005:
        raise StatementMismatch(
            f"{acct.name} held {held:.2f} on {statement.start - timedelta(days=1)}, "
            f"but the statement opens at {statement.opening:.2f}"
        )


def import_statement(
    book: Book, account: str, path: Path | str, *, dry_run: bool = False
) -> ImportResult:
    path = Path(path)
    try:
        text = path.read_text("utf-8")
    except OSError as error:
        raise ImportProblem(f"can't read {path}: {error}") from None
    statement = parse_statement(text)
    acct = book.account(account)
    if statement.currency != acct.currency:
        raise ImportProblem(f"statement is in {statement.currency}, {acct.name} is in {acct.currency}")
    check_totals(statement)
    check_opening(book, acct.id, statement)
    return commit_rows(book, acct.id, statement.entries, path.name, dry_run=dry_run)
