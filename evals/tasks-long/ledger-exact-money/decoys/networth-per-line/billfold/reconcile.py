"""Reconciling an account against a bank statement.

You tick off (clear) the transactions that appear on the statement; the account is
reconciled when the opening balance plus the cleared transactions up to the statement
date equals the statement's closing balance.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from .money import format_amount, to_amount

if TYPE_CHECKING:
    from .book import Book


@dataclass
class Reconciliation:
    account: str
    currency: str
    on: date
    statement_balance: Decimal
    cleared_balance: Decimal
    uncleared: list[str]

    @property
    def difference(self) -> Decimal:
        return self.statement_balance - self.cleared_balance

    @property
    def balanced(self) -> bool:
        return self.difference == 0

    def describe(self) -> str:
        if self.balanced:
            return f"{self.account} is reconciled at {format_amount(self.cleared_balance, self.currency)}"
        return (
            f"{self.account} is off by {format_amount(self.difference, self.currency, plus=True)}"
            f" ({len(self.uncleared)} uncleared)"
        )


def cleared_balance(book: Book, account: str, on: date) -> Decimal:
    acct = book.account(account)
    total = acct.opening_balance
    for txn in book.transactions_for(acct, end=on):
        if txn.cleared:
            total += txn.amount
    return total


def reconcile(book: Book, account: str, statement_balance: object, on: date) -> Reconciliation:
    acct = book.account(account)
    statement = to_amount(statement_balance, acct.currency)
    uncleared = [t.id for t in book.transactions_for(acct, end=on) if not t.cleared]
    return Reconciliation(
        account=acct.name,
        currency=acct.currency,
        on=on,
        statement_balance=statement,
        cleared_balance=cleared_balance(book, acct.id, on),
        uncleared=uncleared,
    )


def mark_cleared(book: Book, txn_ids: Iterable[str], cleared: bool = True) -> int:
    changed = 0
    for txn_id in txn_ids:
        if book.transaction(txn_id).cleared != cleared:
            book.edit_transaction(txn_id, cleared=cleared)
            changed += 1
    return changed
