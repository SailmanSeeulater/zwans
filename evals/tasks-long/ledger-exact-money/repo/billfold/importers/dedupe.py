"""Spotting rows that are already in the account, so importing a file twice is harmless.

A row is a duplicate when its reference (bank transaction id) was imported before, or,
for files without references, when the account already has a transaction on the same
day with the same amount and payee that no earlier row has claimed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Transaction
    from .base import ImportedRow

_NOISE = re.compile(r"[^a-z]+")


def payee_key(payee: str) -> str:
    """'REWE Markt 1234 Berlin' and 'Rewe markt 5678 berlin' are the same shop."""
    return _NOISE.sub("", payee.casefold())


def row_key(day, amount, payee: str) -> tuple:
    return day, round(amount, 2), payee_key(payee)


def find_duplicates(existing: Sequence[Transaction], rows: Sequence[ImportedRow]) -> set[int]:
    refs = {t.import_ref for t in existing if t.import_ref}
    available = Counter(row_key(t.date, t.amount, t.payee) for t in existing)
    duplicates = set()
    for index, row in enumerate(rows):
        if row.ref and row.ref in refs:
            duplicates.add(index)
            continue
        if row.ref and any(t.import_ref for t in existing):
            continue
        key = row_key(row.date, row.amount, row.payee)
        if available[key] > 0:
            available[key] -= 1
            duplicates.add(index)
    return duplicates
