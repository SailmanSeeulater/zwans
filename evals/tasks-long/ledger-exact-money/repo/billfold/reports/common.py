"""What the reports share: picking the transactions a report is about."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING

from ..categories import top_level

if TYPE_CHECKING:
    from ..book import Book
    from ..models import Transaction

UNCATEGORISED = "(uncategorised)"


def report_currency(book: Book, currency: str | None) -> str:
    return (currency or book.settings.base_currency).upper()


def in_currency(book: Book, currency: str, start: date, end: date) -> Iterator[Transaction]:
    """Non-transfer transactions in accounts of `currency` between two days."""
    for txn in book.transactions_for(start=start, end=end):
        if txn.is_transfer:
            continue
        if book.accounts[txn.account].currency != currency:
            continue
        yield txn


def category_label(category: str | None, depth: int | None) -> str:
    if category is None:
        return UNCATEGORISED
    if depth == 1:
        return top_level(category)
    return category
