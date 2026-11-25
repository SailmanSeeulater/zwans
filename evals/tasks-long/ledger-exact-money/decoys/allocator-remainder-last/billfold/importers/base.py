"""What every importer produces, and how imported rows become transactions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from ..errors import ImportProblem, MoneyError
from .dedupe import find_duplicates

if TYPE_CHECKING:
    from ..book import Book
    from ..models import Transaction


@dataclass
class ImportedRow:
    date: date
    amount: Decimal
    payee: str = ""
    memo: str = ""
    category: str | None = None
    ref: str | None = None
    line: int | None = None


@dataclass
class ImportResult:
    source: str
    added: list[Transaction] = field(default_factory=list)
    duplicates: list[ImportedRow] = field(default_factory=list)
    skipped: list[tuple[ImportedRow, str]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{len(self.added)} added"]
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} already there")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return f"{self.source}: " + ", ".join(parts)


def commit_rows(
    book: Book,
    account: str,
    rows: Sequence[ImportedRow],
    source: str,
    *,
    dry_run: bool = False,
) -> ImportResult:
    """Add the rows that aren't already in the account, running the rules on them.

    The whole import is one change: one undo step takes it all back.
    """
    acct = book.account(account)
    result = ImportResult(source)
    duplicate_rows = find_duplicates(book.transactions_for(acct), rows)
    built = []
    for index, row in enumerate(rows):
        if index in duplicate_rows:
            result.duplicates.append(row)
            continue
        if row.date < (acct.opened or row.date):
            result.skipped.append((row, f"before {acct.name} was opened"))
            continue
        try:
            txn = book.new_transaction(
                acct, row.date, row.amount, row.payee, row.memo, row.category,
                import_ref=row.ref,
            )
        except MoneyError as error:
            raise ImportProblem(str(error), row.line) from None
        built.append(txn)
    if built and not dry_run:
        book.commit(built, "import", f"imported {len(built)} from {source}")
    result.added = built
    return result
