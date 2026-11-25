"""Upgrading documents written by older releases to the current layout.

Version 1 (billfold 0.x) kept one currency for the whole file, accounts keyed by name
with their entries nested inside, budgets as {month: {category: amount}} and rates as
{"EUR/USD": {date: rate}}. Version 2 is the flat layout with ids that serialize.py reads.
"""

from __future__ import annotations

from ..errors import StorageError

CURRENT_VERSION = 2


def upgrade_v1(doc: dict) -> dict:
    currency = doc.get("currency", "EUR")
    counters: dict[str, int] = {}

    def new_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    accounts, transactions, categories = [], [], set()
    for name, data in doc.get("accounts", {}).items():
        account_id = new_id("acc")
        accounts.append({
            "id": account_id,
            "name": name,
            "currency": currency,
            "kind": data.get("type", "checking"),
            "opening_balance": data.get("opening", 0.0),
            "opened": data.get("opened"),
            "closed": data.get("closed", False),
            "notes": "",
        })
        for entry in data.get("entries", []):
            category = entry.get("category") or None
            if category:
                categories.add(category)
            transactions.append({
                "id": new_id("txn"),
                "account": account_id,
                "date": entry["date"],
                "amount": entry["amount"],
                "payee": entry.get("payee", ""),
                "memo": entry.get("memo", ""),
                "category": category,
                "cleared": entry.get("cleared", False),
            })
    budgets = [
        {"category": category, "month": month, "amount": amount, "rollover": False}
        for month, row in sorted(doc.get("budgets", {}).items())
        for category, amount in sorted(row.items())
    ]
    rates = []
    for pair, series in sorted(doc.get("rates", {}).items()):
        base, _, quote = pair.partition("/")
        for day, rate in sorted(series.items()):
            rates.append({"base": base, "quote": quote, "date": day, "rate": rate})
    transactions.sort(key=lambda t: t["date"])
    return {
        "version": 2,
        "app": "billfold",
        "settings": {"base_currency": currency, "large_transaction": None, "history_limit": 50},
        "counters": counters,
        "accounts": accounts,
        "categories": sorted(categories),
        "transactions": transactions,
        "budgets": budgets,
        "rules": [],
        "recurring": [],
        "rates": rates,
        "balances": {},
        "history": [],
    }


UPGRADES = {1: upgrade_v1}


def upgrade(doc: dict) -> dict:
    """Bring a document up to CURRENT_VERSION, one version at a time."""
    if not isinstance(doc, dict):
        raise StorageError("not a billfold data file")
    version = doc.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise StorageError(f"unreadable file version {version!r}")
    if version > CURRENT_VERSION:
        raise StorageError(
            f"this file was written by a newer billfold (version {version}); please upgrade"
        )
    while version < CURRENT_VERSION:
        doc = UPGRADES[version](doc)
        version = doc["version"]
    return doc
