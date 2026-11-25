"""Printing for the CLI: tables for people, JSON for scripts."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import TextIO

from ..models import Transaction
from ..money import format_amount
from ..reports.render import table


def out(text: str = "", stream: TextIO | None = None) -> None:
    print(text, file=stream or sys.stdout)


def err(text: str) -> None:
    print(text, file=sys.stderr)


def emit_json(data: object) -> None:
    out(json.dumps(data, indent=2, ensure_ascii=False))


def transactions_table(txns: Sequence[Transaction], currencies: dict[str, str],
                       names: dict[str, str]) -> str:
    rows = []
    for txn in txns:
        currency = currencies[txn.account]
        if txn.splits:
            category = " | ".join(s.category or "?" for s in txn.splits)
        else:
            category = txn.category or ""
        rows.append((
            txn.id,
            txn.date.isoformat(),
            names[txn.account],
            txn.payee,
            category,
            format_amount(txn.amount, currency),
        ))
    return table(("Id", "Date", "Account", "Payee", "Category", "Amount"), rows, "lllllr")


def transaction_json(txn: Transaction) -> dict:
    data = {
        "id": txn.id,
        "account": txn.account,
        "date": txn.date.isoformat(),
        "amount": txn.amount,
        "payee": txn.payee,
        "memo": txn.memo,
        "category": txn.category,
    }
    if txn.splits:
        data["splits"] = [{"category": s.category, "amount": s.amount} for s in txn.splits]
    return data
