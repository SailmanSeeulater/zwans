"""Upgrading documents written by older releases to the current layout.

Version 1 (billfold 0.x) kept one currency for the whole file, accounts keyed by name
with their entries nested inside, budgets as {month: {category: amount}} and rates as
{"EUR/USD": {date: rate}}. Version 2 is the flat layout with ids, with amounts as JSON
numbers (binary floats). Version 3 is the same layout with every amount a string holding
exactly its currency's places, which is what serialize.py reads.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..errors import StorageError
from ..money import amount_text, round_half_up

CURRENT_VERSION = 3


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


def _decimal(value) -> Decimal:
    """A number from an old file: floats are taken at their shortest repr (0.1 is 0.1)."""
    if isinstance(value, bool):
        raise StorageError(f"not an amount: {value!r}")
    try:
        if isinstance(value, float):
            return Decimal(repr(value))
        return Decimal(str(value))
    except InvalidOperation:
        raise StorageError(f"not an amount: {value!r}") from None


def legacy_amount(value, currency: str) -> str:
    """An old file's amount, rounded half away from zero to its currency's places."""
    return amount_text(round_half_up(_decimal(value), currency), currency)


def _snapshot_v3(data: dict, currencies: dict[str, str], base: str) -> dict:
    currency = currencies.get(data.get("account", ""), base)
    data = dict(data)
    if "amount" in data:
        data["amount"] = legacy_amount(data["amount"], currency)
    data["splits"] = [
        {**piece, "amount": legacy_amount(piece["amount"], currency)}
        for piece in data.get("splits", [])
    ]
    return data


def upgrade_v2(doc: dict) -> dict:
    doc = dict(doc)
    settings = dict(doc.get("settings", {}))
    base = settings.get("base_currency", "EUR")
    if settings.get("large_transaction") is not None:
        settings["large_transaction"] = legacy_amount(settings["large_transaction"], base)
    doc["settings"] = settings
    currencies = {a["id"]: a.get("currency", "EUR") for a in doc.get("accounts", [])}

    accounts = []
    for account in doc.get("accounts", []):
        account = dict(account)
        account["opening_balance"] = legacy_amount(
            account.get("opening_balance", 0), account.get("currency", "EUR")
        )
        accounts.append(account)
    doc["accounts"] = accounts
    doc["transactions"] = [_snapshot_v3(t, currencies, base) for t in doc.get("transactions", [])]
    doc["budgets"] = [
        {**b, "amount": legacy_amount(b["amount"], base)} for b in doc.get("budgets", [])
    ]
    doc["recurring"] = [
        {**e, "amount": legacy_amount(e["amount"], currencies.get(e["account"], base))}
        for e in doc.get("recurring", [])
    ]
    doc["rates"] = [{**r, "rate": str(_decimal(r["rate"]))} for r in doc.get("rates", [])]
    rules = []
    for rule in doc.get("rules", []):
        rule = dict(rule)
        if rule.get("split"):
            rule["split"] = {k: str(_decimal(v)) for k, v in rule["split"].items()}
        rules.append(rule)
    doc["rules"] = rules
    doc["history"] = [
        {
            **entry,
            "before": [_snapshot_v3(t, currencies, base) for t in entry.get("before", [])],
            "after": [_snapshot_v3(t, currencies, base) for t in entry.get("after", [])],
        }
        for entry in doc.get("history", [])
    ]
    doc["version"] = 3
    return doc


UPGRADES = {1: upgrade_v1, 2: upgrade_v2}


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
