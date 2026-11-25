"""Alerts: a category going over its budget, an unusually large transaction.

The book emits an event dict for each alert. Subscribers (callbacks) get it first; sinks
then record it. The CLI adds a JSON-lines sink writing to `alerts.jsonl` next to the data
file, which other tools (a phone notifier, a mail script) tail.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from decimal import Decimal

from .models import Account, Transaction
from .money import amount_text

Event = dict[str, object]
BUDGET_EXCEEDED = "budget.exceeded"
LARGE_TRANSACTION = "transaction.large"


class Sink(Protocol):
    def write(self, event: Event) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def write(self, event: Event) -> None:
        self.events.append(event)


class JsonlSink:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def write(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def read_jsonl(path: Path | str) -> list[Event]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


class Notifier:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self._sinks: list[Sink] = []
        self.muted = False

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def add_sink(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def emit(self, kind: str, payload: Event) -> Event:
        event: Event = {"type": kind, **payload}
        if self.muted:
            return event
        for callback in list(self._subscribers):
            callback(dict(event))
        for sink in self._sinks:
            sink.write(dict(event))
        return event


def budget_exceeded_payload(
    category: str, month: str, budgeted: Decimal, spent: Decimal, currency: str
) -> Event:
    return {
        "category": category,
        "month": month,
        "currency": currency,
        "budget": float(budgeted),
        "spent": float(spent),
        "over_by": float(spent - budgeted),
    }


def large_transaction_payload(txn: Transaction, account: Account, threshold: Decimal) -> Event:
    currency = account.currency
    return {
        "transaction": txn.id,
        "account": account.name,
        "date": txn.date.isoformat(),
        "payee": txn.payee,
        "currency": account.currency,
        "amount": float(txn.amount),
        "threshold": float(threshold),
    }
