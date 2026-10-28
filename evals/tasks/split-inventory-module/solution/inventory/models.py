"""The records the warehouse keeps."""


class UnknownSku(KeyError):
    """Raised when a SKU is not stocked."""

    def __init__(self, sku: str) -> None:
        super().__init__(sku)
        self.sku = sku

    def __str__(self) -> str:
        return f"unknown SKU {self.sku!r}"


class InsufficientStock(Exception):
    """Raised when shipping more units than are on hand."""

    def __init__(self, sku: str, wanted: int, available: int) -> None:
        super().__init__(f"{sku}: wanted {wanted}, only {available} on hand")
        self.sku = sku
        self.wanted = wanted
        self.available = available


class Item:
    """One stocked product."""

    def __init__(self, sku: str, name: str, unit_cost_cents: int, quantity: int = 0) -> None:
        if unit_cost_cents < 0:
            raise ValueError("unit cost cannot be negative")
        self.sku = sku.upper()
        self.name = name
        self.unit_cost_cents = unit_cost_cents
        self.quantity = quantity

    def __repr__(self) -> str:
        return f"Item({self.sku!r}, {self.name!r}, {self.unit_cost_cents}, {self.quantity})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Item):
            return NotImplemented
        return (self.sku, self.name, self.unit_cost_cents, self.quantity) == (
            other.sku,
            other.name,
            other.unit_cost_cents,
            other.quantity,
        )

    @property
    def value_cents(self) -> int:
        return self.unit_cost_cents * self.quantity


class StockMovement:
    """A change to an item's quantity, kept for the audit trail."""

    def __init__(self, sku: str, delta: int, reason: str) -> None:
        self.sku = sku
        self.delta = delta
        self.reason = reason

    def __repr__(self) -> str:
        return f"StockMovement({self.sku!r}, {self.delta}, {self.reason!r})"
