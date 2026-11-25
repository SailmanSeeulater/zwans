"""QIF export, the old Quicken interchange format many desktop apps still import.

One !Account block per account, then its transactions. Dates are written MM/DD/YYYY,
split transactions get S/$/E lines, and the opening balance is the first entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..book import Book
    from ..models import Account, Transaction

_TYPES = {"checking": "Bank", "savings": "Bank", "cash": "Cash", "credit": "CCard",
          "investment": "Bank"}


def _amount(value: float) -> str:
    return "%.2f" % value


def _date(day) -> str:
    return day.strftime("%m/%d/%Y")


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def _transaction_lines(txn: Transaction) -> list[str]:
    lines = [f"D{_date(txn.date)}", f"T{_amount(txn.amount)}"]
    if txn.cleared:
        lines.append("CX")
    if txn.payee:
        lines.append(f"P{_clean(txn.payee)}")
    if txn.memo:
        lines.append(f"M{_clean(txn.memo)}")
    if txn.splits:
        for split in txn.splits:
            lines.append(f"S{split.category or ''}")
            if split.memo:
                lines.append(f"E{_clean(split.memo)}")
            lines.append(f"${_amount(split.amount)}")
    elif txn.category:
        lines.append(f"L{txn.category}")
    lines.append("^")
    return lines


def account_lines(book: Book, account: Account) -> list[str]:
    qif_type = _TYPES.get(account.kind, "Bank")
    lines = ["!Account", f"N{account.name}", f"T{qif_type}", "^", f"!Type:{qif_type}"]
    opened = account.opened or min(
        (t.date for t in book.transactions_for(account)), default=None
    )
    if opened is not None:
        lines += [f"D{_date(opened)}", f"T{_amount(account.opening_balance)}",
                  "POpening Balance", f"L[{account.name}]", "^"]
    for txn in book.transactions_for(account):
        lines.extend(_transaction_lines(txn))
    return lines


def qif_text(book: Book, account: str | None = None) -> str:
    accounts = [book.account(account)] if account else book.list_accounts(include_closed=True)
    lines: list[str] = []
    for acct in accounts:
        lines.extend(account_lines(book, acct))
    return "\n".join(lines) + "\n"


def export_qif(book: Book, path: Path | str, account: str | None = None) -> int:
    text = qif_text(book, account)
    Path(path).write_text(text, "utf-8")
    return text.count("\n^")
