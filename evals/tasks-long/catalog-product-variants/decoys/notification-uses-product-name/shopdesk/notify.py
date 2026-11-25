"""Notifications for the people who restock and pack: an outbox of messages.

Listeners turn events into messages kept in the data file until something delivers them
(`shopdesk outbox flush` writes them out as JSON lines for the mailer to pick up).
"""

import json
from collections.abc import Callable
from typing import Any

from shopdesk.catalog.products import ProductCatalog
from shopdesk.clock import Clock
from shopdesk.config import Settings
from shopdesk.events import EventBus
from shopdesk.models import Notification, ShopData
from shopdesk.money import format_money
from shopdesk.stock.ledger import StockLedger

Sender = Callable[[Notification], None]


class Notifier:
    def __init__(
        self,
        data: ShopData,
        catalog: ProductCatalog,
        ledger: StockLedger,
        settings: Settings,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._data = data
        self._catalog = catalog
        self._ledger = ledger
        self._settings = settings
        self._bus = bus
        self._clock = clock

    def attach(self) -> None:
        self._bus.subscribe("stock.low", self._on_low_stock)
        self._bus.subscribe("order.placed", self._on_order)
        self._bus.subscribe("order.cancelled", self._on_order)

    def _queue(self, topic: str, payload: dict[str, Any]) -> Notification:
        note = Notification(self._data.next_id("notification"), self._clock(), topic, payload)
        self._data.outbox.append(note)
        return note

    def _on_low_stock(self, topic: str, payload: dict[str, Any]) -> None:
        product, variant = self._catalog.resolve(payload["sku"])
        self._queue(
            "stock.low",
            {
                "sku": variant.sku,
                "name": product.name,
                "stock": payload["stock"],
                "reorder_level": payload["reorder_level"],
                "warehouses": self._ledger.by_warehouse(variant.sku),
                "supplier": product.supplier,
            },
        )

    def _on_order(self, topic: str, payload: dict[str, Any]) -> None:
        order = self._data.orders[payload["number"]]
        self._queue(
            topic,
            {
                "number": order.number,
                "customer": order.customer,
                "total": format_money(order.total, self._settings.currency),
                "lines": [
                    {"sku": line.sku, "name": line.name, "qty": line.qty} for line in order.lines
                ],
            },
        )

    def pending(self) -> list[Notification]:
        return [n for n in self._data.outbox if n.sent_at is None]

    def all(self) -> list[Notification]:
        return list(self._data.outbox)

    def flush(self, send: Sender) -> int:
        """Hand every pending message to `send`, marking each sent once it returns."""
        sent = 0
        for note in self.pending():
            send(note)
            note.sent_at = self._clock()
            sent += 1
        return sent


def as_json_line(note: Notification) -> str:
    return json.dumps(
        {"id": note.id, "at": note.at, "topic": note.topic, "payload": note.payload},
        sort_keys=True,
    )
