"""Reconciling an account against a bank statement.

You tick off (clear) the transactions that appear on the statement; the account is
reconciled when the opening balance plus the cleared transactions up to the statement
date equals the statement's closing balance.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from .money import format_amount, parse_amount, round_money

if TYPE_CHECKING:
    from .book import Book


@dataclass
class Reconciliation:
    account: str
    currency: str
    on: date
    statement_balance: float
    cleared_balance: float
    uncleared: list[str]

    @property
    def difference(self) -> float:
        return round_money(self.statement_balance - self.cleared_balance, self.currency)

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


def cleared_balance(book: Book, account: str, on: date) -> float:
    acct = book.account(account)
    total = float(acct.opening_balance)
    for txn in book.transactions_for(acct, end=on):
        if txn.cleared:
            total += float(txn.amount)
    return total


def reconcile(book: Book, account: str, statement_balance: object, on: date) -> Reconciliation:
    acct = book.account(account)
    statement = round_money(parse_amount(statement_balance), acct.currency)
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
