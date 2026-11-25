"""CSV export: one row per transaction (one per piece for split ones), with a running
balance per account, for spreadsheets."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from ..book import Book

COLUMNS = ("date", "account", "payee", "category", "memo", "amount", "currency", "balance", "id")


def _rows(book: Book, account: str | None, start: date | None, end: date | None):
    accounts = [book.account(account)] if account else book.list_accounts(include_closed=True)
    for acct in accounts:
        if start is not None:
            running = book.balance(acct, start - timedelta(days=1))
        else:
            running = acct.opening_balance
        for txn in book.transactions_for(acct, start, end):
            for category, amount in txn.category_amounts():
                running += amount
                yield {
                    "date": txn.date.isoformat(),
                    "account": acct.name,
                    "payee": txn.payee,
                    "category": category or "",
                    "memo": txn.memo,
                    "amount": f"{amount:.2f}",
                    "currency": acct.currency,
                    "balance": f"{running:.2f}",
                    "id": txn.id,
                }


def write_csv(
    book: Book,
    out: TextIO,
    account: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> int:
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    count = 0
    for row in _rows(book, account, start, end):
        writer.writerow(row)
        count += 1
    return count


def export_csv(book: Book, path: Path | str, **options) -> int:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        return write_csv(book, handle, **options)


def csv_text(book: Book, **options) -> str:
    buffer = io.StringIO()
    write_csv(book, buffer, **options)
    return buffer.getvalue()
