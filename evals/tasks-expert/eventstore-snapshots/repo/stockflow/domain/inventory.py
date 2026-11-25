"""Stock items: how many units we hold of a SKU, and how many are promised to orders."""

from typing import Any

from stockflow.aggregate import Aggregate, handles
from stockflow.domain.events import (
    ItemRegistered,
    ReservationReleased,
    StockAdjusted,
    StockReceived,
    StockReserved,
    StockShipped,
)
from stockflow.errors import DomainError


class StockItem(Aggregate):
    stream_prefix = "item"

    def __init__(self, sku: str) -> None:
        super().__init__(sku)
        self.registered = False
        self.name: str | None = None
        self.reorder_level = 0
        self.on_hand = 0
        self.reservations: dict[str, int] = {}  # order id -> units promised to it
        self.lots: dict[str, int] = {}  # lot -> units received in it
        self.shipped = 0

    @property
    def reserved(self) -> int:
        return sum(self.reservations.values())

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    # -- commands

    def register(self, name: str, reorder_level: int = 0) -> None:
        if self.registered:
            raise DomainError(f"{self.id} is already registered")
        if not name.strip():
            raise DomainError("an item needs a name")
        if reorder_level < 0:
            raise DomainError("the reorder level can't be negative")
        self._record(ItemRegistered(self.id, name.strip(), reorder_level))

    def receive(self, quantity: int, lot: str) -> None:
        self._must_be_registered()
        if quantity <= 0:
            raise DomainError("received quantity must be positive")
        if not lot.strip():
            raise DomainError("received stock needs a lot")
        self._record(StockReceived(quantity, lot.strip()))

    def reserve(self, order_id: str, quantity: int) -> None:
        self._must_be_registered()
        if quantity <= 0:
            raise DomainError("reserved quantity must be positive")
        if order_id in self.reservations:
            raise DomainError(f"{self.id} is already reserved for order {order_id}")
        if quantity > self.available:
            raise DomainError(
                f"only {self.available} of {self.id} available, order {order_id} wants {quantity}"
            )
        self._record(StockReserved(order_id, quantity))

    def release(self, order_id: str) -> None:
        if order_id not in self.reservations:
            raise DomainError(f"{self.id} has no reservation for order {order_id}")
        self._record(ReservationReleased(order_id))

    def ship(self, order_id: str) -> None:
        if order_id not in self.reservations:
            raise DomainError(f"{self.id} has nothing reserved for order {order_id}")
        self._record(StockShipped(order_id))

    def adjust(self, delta: int, reason: str) -> None:
        self._must_be_registered()
        if delta == 0:
            raise DomainError("an adjustment of 0 changes nothing")
        if not reason.strip():
            raise DomainError("adjustments need a reason")
        if self.on_hand + delta < self.reserved:
            raise DomainError(
                f"{self.id}: can't go to {self.on_hand + delta} on hand with {self.reserved} reserved"
            )
        self._record(StockAdjusted(delta, reason.strip()))

    def _must_be_registered(self) -> None:
        if not self.registered:
            raise DomainError(f"{self.id} is not registered")

    # -- handlers

    @handles(ItemRegistered)
    def when_registered(self, event: ItemRegistered) -> None:
        self.registered = True
        self.name = event.name
        self.reorder_level = event.reorder_level

    @handles(StockReceived)
    def when_received(self, event: StockReceived) -> None:
        self.on_hand += event.quantity
        self.lots[event.lot] = self.lots.get(event.lot, 0) + event.quantity

    @handles(StockReserved)
    def when_reserved(self, event: StockReserved) -> None:
        self.reservations[event.order_id] = event.quantity

    @handles(ReservationReleased)
    def when_released(self, event: ReservationReleased) -> None:
        self.reservations.pop(event.order_id, None)

    @handles(StockShipped)
    def when_shipped(self, event: StockShipped) -> None:
        quantity = self.reservations.pop(event.order_id, 0)
        self.on_hand -= quantity
        self.shipped += quantity

    @handles(StockAdjusted)
    def when_adjusted(self, event: StockAdjusted) -> None:
        self.on_hand += event.delta

    # -- views

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.id,
            "name": self.name,
            "reorder_level": self.reorder_level,
            "on_hand": self.on_hand,
            "reserved": self.reserved,
            "available": self.available,
            "reservations": dict(sorted(self.reservations.items())),
            "lots": dict(sorted(self.lots.items())),
            "shipped": self.shipped,
        }
