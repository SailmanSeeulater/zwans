"""JSON export: accounts with their balances and every transaction, for other tools.

Unlike the data file this is meant to be read by other programs, so it is flat and
stable: no history, caches or rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..clock import stamp
from ..money import amount_text

if TYPE_CHECKING:
    from ..book import Book

FORMAT = "billfold-export/1"


def export_document(book: Book) -> dict:
    accounts = []
    for account in book.list_accounts(include_closed=True):
        currency = account.currency
        accounts.append({
            "id": account.id,
            "name": account.name,
            "currency": account.currency,
            "kind": account.kind,
            "opening_balance": amount_text(account.opening_balance, currency),
            "balance": amount_text(book.balance(account), currency),
            "closed": account.closed,
        })
    transactions = []
    for txn in book.transactions_for():
        currency = book.accounts[txn.account].currency
        item = {
            "id": txn.id,
            "account": txn.account,
            "date": txn.date.isoformat(),
            "amount": amount_text(txn.amount, currency),
            "payee": txn.payee,
            "memo": txn.memo,
            "category": txn.category,
            "tags": list(txn.tags),
        }
        if txn.splits:
            item["splits"] = [
                {"category": s.category, "amount": amount_text(s.amount, currency),
                 "memo": s.memo}
                for s in txn.splits
            ]
        if txn.transfer_id:
            item["transfer"] = txn.transfer_id
        transactions.append(item)
    return {
        "format": FORMAT,
        "exported": stamp(book.clock.now()),
        "base_currency": book.settings.base_currency,
        "accounts": accounts,
        "transactions": transactions,
    }


def export_json(book: Book, path: Path | str) -> int:
    doc = export_document(book)
    Path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return len(doc["transactions"])
