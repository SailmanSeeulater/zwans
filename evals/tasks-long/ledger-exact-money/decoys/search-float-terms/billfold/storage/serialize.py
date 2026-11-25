"""Turning a Book into the data file's document and back (current version only)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from ..audit import History
from ..categories import CategoryTree
from ..ids import IdSource
from ..models import Account, Budget, RecurringEntry, Rule, Settings, Split, Transaction
from ..money import amount_text, decimal_number, to_amount
from ..rules import condition_text, parse_condition

if TYPE_CHECKING:
    from ..book import Book


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _amount(value, currency: str) -> Decimal:
    return to_amount(value, currency)


# -- writing --------------------------------------------------------------------------


def account_to_dict(account: Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "currency": account.currency,
        "kind": account.kind,
        "opening_balance": amount_text(account.opening_balance, account.currency),
        "opened": account.opened.isoformat() if account.opened else None,
        "closed": account.closed,
        "notes": account.notes,
    }


def transaction_to_dict(txn: Transaction, currency: str) -> dict:
    data = {
        "id": txn.id,
        "account": txn.account,
        "date": txn.date.isoformat(),
        "amount": amount_text(txn.amount, currency),
        "payee": txn.payee,
        "memo": txn.memo,
        "category": txn.category,
    }
    if txn.splits:
        data["splits"] = [
            {"category": s.category, "amount": amount_text(s.amount, currency), "memo": s.memo}
            for s in txn.splits
        ]
    if txn.tags:
        data["tags"] = list(txn.tags)
    for key in ("transfer_id", "recurring_id", "import_ref"):
        if getattr(txn, key):
            data[key] = getattr(txn, key)
    if txn.cleared:
        data["cleared"] = True
    return data


def budget_to_dict(budget: Budget, currency: str) -> dict:
    return {
        "category": budget.category,
        "month": budget.month,
        "amount": amount_text(budget.amount, currency),
        "rollover": budget.rollover,
    }


def rule_to_dict(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "conditions": [condition_text(c) for c in rule.conditions],
        "category": rule.set_category,
        "rename": rule.rename_payee,
        "split": {k: str(v) for k, v in rule.split.items()} if rule.split else None,
        "tags": list(rule.add_tags),
        "priority": rule.priority,
        "enabled": rule.enabled,
    }


def recurring_to_dict(entry: RecurringEntry, currency: str) -> dict:
    return {
        "id": entry.id,
        "account": entry.account,
        "payee": entry.payee,
        "amount": amount_text(entry.amount, currency),
        "frequency": entry.frequency,
        "start": entry.start.isoformat(),
        "next_date": entry.next_date.isoformat(),
        "category": entry.category,
        "memo": entry.memo,
        "end": entry.end.isoformat() if entry.end else None,
        "instalments": entry.instalments,
        "done": entry.done,
        "active": entry.active,
    }


def settings_to_dict(settings: Settings) -> dict:
    threshold = settings.large_transaction
    return {
        "base_currency": settings.base_currency,
        "large_transaction": (
            amount_text(threshold, settings.base_currency) if threshold is not None else None
        ),
        "history_limit": settings.history_limit,
    }


def book_to_dict(book: Book, version: int) -> dict:
    def currency(account_id: str) -> str:
        return book.accounts[account_id].currency

    base = book.settings.base_currency
    balances = {}
    for account_id, (value, count) in book.balances.snapshot().items():
        if account_id in book.accounts:
            balances[account_id] = {"amount": amount_text(value, currency(account_id)),
                                    "count": count}
    return {
        "version": version,
        "app": "billfold",
        "settings": settings_to_dict(book.settings),
        "counters": book.ids.to_dict(),
        "accounts": [account_to_dict(a) for a in book.accounts.values()],
        "categories": book.categories.names(),
        "transactions": [
            transaction_to_dict(t, currency(t.account)) for t in book.transactions_for()
        ],
        "budgets": [budget_to_dict(b, base) for b in book.budgets.all()],
        "rules": [rule_to_dict(r) for r in book.rules.values()],
        "recurring": [recurring_to_dict(e, currency(e.account)) for e in book.recurring.all()],
        "rates": [
            {"base": r.base, "quote": r.quote, "date": r.on.isoformat(), "rate": str(r.rate)}
            for r in book.rates.all()
        ],
        "balances": balances,
        "history": book.history.to_list(),
    }


# -- reading --------------------------------------------------------------------------


def account_from_dict(data: dict) -> Account:
    currency = data.get("currency", "EUR")
    return Account(
        id=data["id"],
        name=data["name"],
        currency=currency,
        kind=data.get("kind", "checking"),
        opening_balance=_amount(data.get("opening_balance", "0"), currency),
        opened=_day(data.get("opened")),
        closed=bool(data.get("closed", False)),
        notes=data.get("notes", ""),
    )


def transaction_from_dict(data: dict, currency: str) -> Transaction:
    return Transaction(
        id=data["id"],
        account=data["account"],
        date=date.fromisoformat(data["date"]),
        amount=_amount(data["amount"], currency),
        payee=data.get("payee", ""),
        memo=data.get("memo", ""),
        category=data.get("category"),
        splits=[
            Split(s.get("category"), _amount(s["amount"], currency), s.get("memo", ""))
            for s in data.get("splits", [])
        ],
        tags=list(data.get("tags", [])),
        transfer_id=data.get("transfer_id"),
        recurring_id=data.get("recurring_id"),
        cleared=bool(data.get("cleared", False)),
        import_ref=data.get("import_ref"),
    )


def rule_from_dict(data: dict) -> Rule:
    split = data.get("split")
    return Rule(
        id=data["id"],
        name=data.get("name", data["id"]),
        conditions=[parse_condition(text) for text in data.get("conditions", [])],
        set_category=data.get("category"),
        rename_payee=data.get("rename"),
        split={k: decimal_number(v, "percentage") for k, v in split.items()} if split else None,
        add_tags=list(data.get("tags", [])),
        priority=int(data.get("priority", 100)),
        enabled=bool(data.get("enabled", True)),
    )


def recurring_from_dict(data: dict, currency: str) -> RecurringEntry:
    return RecurringEntry(
        id=data["id"],
        account=data["account"],
        payee=data.get("payee", ""),
        amount=_amount(data["amount"], currency),
        frequency=data["frequency"],
        start=date.fromisoformat(data["start"]),
        next_date=date.fromisoformat(data["next_date"]),
        category=data.get("category"),
        memo=data.get("memo", ""),
        end=_day(data.get("end")),
        instalments=data.get("instalments"),
        done=int(data.get("done", 0)),
        active=bool(data.get("active", True)),
    )


def fill_book(book: Book, doc: dict) -> Book:
    settings = doc.get("settings", {})
    threshold = settings.get("large_transaction")
    base = settings.get("base_currency", "EUR")
    book.settings = Settings(
        base_currency=base,
        large_transaction=_amount(threshold, base) if threshold is not None else None,
        history_limit=int(settings.get("history_limit", 50)),
    )
    book.ids = IdSource(doc.get("counters", {}))
    book.categories = CategoryTree(doc.get("categories", []))
    for data in doc.get("accounts", []):
        account = account_from_dict(data)
        book.accounts[account.id] = account
        book.ids.seen(account.id)
    for data in doc.get("transactions", []):
        txn = transaction_from_dict(data, book.accounts[data["account"]].currency)
        book.transactions[txn.id] = txn
        book.ids.seen(txn.id)
        for name, _ in txn.category_amounts():
            book.categories.ensure(name)
    for data in doc.get("budgets", []):
        book.budgets.load(
            Budget(data["category"], data["month"], _amount(data["amount"], base),
                   bool(data.get("rollover", False)))
        )
    for data in doc.get("rules", []):
        rule = rule_from_dict(data)
        book.rules[rule.id] = rule
        book.ids.seen(rule.id)
    for data in doc.get("recurring", []):
        entry = recurring_from_dict(data, book.accounts[data["account"]].currency)
        book.recurring.load(entry)
        book.ids.seen(entry.id)
    for data in doc.get("rates", []):
        book.rates.set(data["base"], data["quote"], data["rate"], date.fromisoformat(data["date"]))
    book.history = History.from_list(doc.get("history", []), book.settings.history_limit)
    book.rebuild_caches()
    for account_id, entry in doc.get("balances", {}).items():
        if account_id in book.accounts:
            currency = book.accounts[account_id].currency
            book.balances.put(account_id, _amount(entry["amount"], currency), int(entry["count"]))
    return book
