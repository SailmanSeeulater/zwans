"""Wiring: builds a ready-to-use orderdesk on top of a data folder (or in memory)."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import handlers  # noqa: F401  (registers every command)
from .audit import AuditLog
from .bus import EventBus
from .dispatcher import Desk
from .notifications import Notifier, Outbox
from .projections import CustomerLedger, OrderList, SalesReport
from .store import JsonlEventStore, MemoryEventStore


def system_clock() -> str:
    """Now, as stamped on events. ORDERDESK_NOW overrides it (for scripts and tests)."""
    fixed = os.environ.get("ORDERDESK_NOW")
    if fixed:
        return fixed
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class App:
    desk: Desk
    store: MemoryEventStore
    orders: OrderList
    sales: SalesReport
    customers: CustomerLedger
    audit: AuditLog
    outbox: Outbox


def open_app(data_dir: Path | str | None = None, *, clock: Callable[[], str] = system_clock) -> App:
    if data_dir is None:
        store: MemoryEventStore = MemoryEventStore()
        audit, outbox = AuditLog(), Outbox()
    else:
        data_dir = Path(data_dir)
        store = JsonlEventStore(data_dir / "events.jsonl")
        audit = AuditLog(data_dir / "audit.jsonl")
        outbox = Outbox(data_dir / "outbox.jsonl")

    bus = EventBus()
    orders, sales, customers = OrderList(), SalesReport(), CustomerLedger()
    for read_model in (orders, sales, customers):
        for ev in store.all_events():
            read_model(ev)
        bus.subscribe(read_model)

    desk = Desk(store, clock=clock, audit=audit, bus=bus)
    bus.subscribe(Notifier(outbox, lookup=desk.state))
    return App(desk, store, orders, sales, customers, audit, outbox)
