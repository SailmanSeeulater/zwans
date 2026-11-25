"""Customer orders: lines of SKUs, from draft to shipped (or cancelled)."""

from typing import Any

from stockflow.aggregate import Aggregate, handles
from stockflow.domain.events import (
    LineAdded,
    LineRemoved,
    OrderCancelled,
    OrderConfirmed,
    OrderPlaced,
    OrderShipped,
)
from stockflow.errors import DomainError

DRAFT = "draft"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
SHIPPED = "shipped"


class Order(Aggregate):
    stream_prefix = "order"
    state_version = 1

    def __init__(self, order_id: str) -> None:
        super().__init__(order_id)
        self.customer: str | None = None
        self.status: str | None = None
        self.lines: dict[str, dict[str, int]] = {}  # sku -> {"quantity", "unit_price_cents"}
        self.cancel_reason: str | None = None

    @property
    def total_cents(self) -> int:
        return sum(line["quantity"] * line["unit_price_cents"] for line in self.lines.values())

    # -- commands

    def place(self, customer: str) -> None:
        if self.status is not None:
            raise DomainError(f"order {self.id} already exists")
        if not customer.strip():
            raise DomainError("an order needs a customer")
        self._record(OrderPlaced(customer.strip()))

    def add_line(self, sku: str, quantity: int, unit_price_cents: int) -> None:
        self._must_be(DRAFT, "add lines to")
        if quantity <= 0:
            raise DomainError("line quantity must be positive")
        if unit_price_cents < 0:
            raise DomainError("prices can't be negative")
        self._record(LineAdded(sku, quantity, unit_price_cents))

    def remove_line(self, sku: str) -> None:
        self._must_be(DRAFT, "remove lines from")
        if sku not in self.lines:
            raise DomainError(f"order {self.id} has no line for {sku}")
        self._record(LineRemoved(sku))

    def confirm(self) -> None:
        self._must_be(DRAFT, "confirm")
        if not self.lines:
            raise DomainError(f"order {self.id} has no lines")
        self._record(OrderConfirmed())

    def cancel(self, reason: str) -> None:
        if self.status not in (DRAFT, CONFIRMED):
            raise DomainError(f"can't cancel order {self.id}: it is {self.status}")
        self._record(OrderCancelled(reason.strip() or "no reason given"))

    def ship(self) -> None:
        self._must_be(CONFIRMED, "ship")
        self._record(OrderShipped())

    def _must_be(self, status: str, doing: str) -> None:
        if self.status != status:
            raise DomainError(f"can't {doing} order {self.id}: it is {self.status or 'not placed'}")

    # -- handlers

    @handles(OrderPlaced)
    def when_placed(self, event: OrderPlaced) -> None:
        self.customer = event.customer
        self.status = DRAFT

    @handles(LineAdded)
    def when_line_added(self, event: LineAdded) -> None:
        line = self.lines.get(event.sku)
        if line is None:
            self.lines[event.sku] = {
                "quantity": event.quantity,
                "unit_price_cents": event.unit_price_cents,
            }
        else:
            line["quantity"] += event.quantity
            line["unit_price_cents"] = event.unit_price_cents

    @handles(LineRemoved)
    def when_line_removed(self, event: LineRemoved) -> None:
        self.lines.pop(event.sku, None)

    @handles(OrderConfirmed)
    def when_confirmed(self, event: OrderConfirmed) -> None:
        self.status = CONFIRMED

    @handles(OrderCancelled)
    def when_cancelled(self, event: OrderCancelled) -> None:
        self.status = CANCELLED
        self.cancel_reason = event.reason

    @handles(OrderShipped)
    def when_shipped(self, event: OrderShipped) -> None:
        self.status = SHIPPED

    # -- views

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "customer": self.customer,
            "status": self.status,
            "lines": {sku: dict(line) for sku, line in sorted(self.lines.items())},
            "total_cents": self.total_cents,
            "cancel_reason": self.cancel_reason,
        }
