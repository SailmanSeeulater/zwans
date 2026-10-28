"""Stock in the warehouse.

on_hand   units physically on the shelves
reserved  units on the shelves that belong to orders not shipped yet
available on_hand - reserved: what a new order can still get

Every change is logged in `movements`, so on_hand can always be explained.
"""

from collections import defaultdict
from dataclasses import dataclass

from .errors import InvalidRequest, OutOfStock


@dataclass(frozen=True)
class Movement:
    kind: str  # "receive" (from a supplier), "ship" (to a customer), "restock" (a return)
    sku: str
    qty: int
    at: str


class Inventory:
    def __init__(self) -> None:
        self._on_hand: defaultdict[str, int] = defaultdict(int)
        self._reserved: defaultdict[str, int] = defaultdict(int)
        self.movements: list[Movement] = []

    def on_hand(self, sku: str) -> int:
        return self._on_hand[sku]

    def reserved(self, sku: str) -> int:
        return self._reserved[sku]

    def available(self, sku: str) -> int:
        return self._on_hand[sku] - self._reserved[sku]

    @staticmethod
    def _check(qty: int) -> None:
        if qty <= 0:
            raise InvalidRequest("quantities must be more than zero")

    def receive(self, sku: str, qty: int, at: str) -> None:
        self._check(qty)
        self._on_hand[sku] += qty
        self.movements.append(Movement("receive", sku, qty, at))

    def reserve(self, sku: str, qty: int) -> None:
        self._check(qty)
        if qty > self.available(sku):
            raise OutOfStock(f"only {self.available(sku)} of {sku} available, {qty} wanted")
        self._reserved[sku] += qty

    def release(self, sku: str, qty: int) -> None:
        """Give reserved units back to the shelf (the order no longer wants them)."""
        self._check(qty)
        if qty > self._reserved[sku]:
            raise ValueError(f"cannot release {qty} of {sku}: only {self._reserved[sku]} reserved")
        self._reserved[sku] -= qty

    def ship(self, sku: str, qty: int, at: str) -> None:
        """Reserved units leave the warehouse."""
        self._check(qty)
        if qty > self._reserved[sku]:
            raise ValueError(f"cannot ship {qty} of {sku}: only {self._reserved[sku]} reserved")
        self._reserved[sku] -= qty
        self._on_hand[sku] -= qty
        self.movements.append(Movement("ship", sku, qty, at))

    def restock(self, sku: str, qty: int, at: str) -> None:
        """Returned units go back on the shelf."""
        self._check(qty)
        self._on_hand[sku] += qty
        self.movements.append(Movement("restock", sku, qty, at))
