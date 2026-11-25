"""JSON export: accounts with their balances and every transaction, for other tools.

Unlike the data file this is meant to be read by other programs, so it is flat and
stable: no history, caches or rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..clock import stamp
from ..currencies import get_currency

if TYPE_CHECKING:
    from ..book import Book

FORMAT = "billfold-export/1"


def export_document(book: Book) -> dict:
    accounts = []
    for account in book.list_accounts(include_closed=True):
        places = get_currency(account.currency).exponent
        accounts.append({
            "id": account.id,
            "name": account.name,
            "currency": account.currency,
            "kind": account.kind,
            "opening_balance": round(account.opening_balance, places),
            "balance": round(book.balance(account), places),
            "closed": account.closed,
        })
    transactions = []
    for txn in book.transactions_for():
        places = get_currency(book.accounts[txn.account].currency).exponent
        item = {
            "id": txn.id,
            "account": txn.account,
            "date": txn.date.isoformat(),
            "amount": round(txn.amount, places),
            "payee": txn.payee,
            "memo": txn.memo,
            "category": txn.category,
            "tags": list(txn.tags),
        }
        if txn.splits:
            item["splits"] = [
                {"category": s.category, "amount": round(s.amount, places), "memo": s.memo}
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
