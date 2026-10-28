"""Stock keeping for a small warehouse: the records, the stock itself, prices and reports."""

import csv
import io
from collections import defaultdict

# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class Warehouse:
    """Items by SKU, plus every movement in the order it happened."""

    def __init__(self) -> None:
        self.items: dict[str, Item] = {}
        self.movements: list[StockMovement] = []

    def add_item(self, item: Item) -> None:
        if item.sku in self.items:
            raise ValueError(f"{item.sku} is already stocked")
        self.items[item.sku] = item
        if item.quantity:
            self.movements.append(StockMovement(item.sku, item.quantity, "opening"))

    def get(self, sku: str) -> Item:
        try:
            return self.items[sku.upper()]
        except KeyError:
            raise UnknownSku(sku.upper()) from None

    def receive(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        item = self.get(sku)
        item.quantity += quantity
        self.movements.append(StockMovement(item.sku, quantity, "received"))

    def ship(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        item = self.get(sku)
        if quantity > item.quantity:
            raise InsufficientStock(item.sku, quantity, item.quantity)
        item.quantity -= quantity
        self.movements.append(StockMovement(item.sku, -quantity, "shipped"))


def load_items(text: str) -> Warehouse:
    """Build a warehouse from CSV with a `sku,name,unit_cost_cents,quantity` header."""
    warehouse = Warehouse()
    for row in csv.DictReader(io.StringIO(text)):
        warehouse.add_item(
            Item(row["sku"], row["name"], int(row["unit_cost_cents"]), int(row["quantity"]))
        )
    return warehouse


def dump_items(warehouse: Warehouse) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["sku", "name", "unit_cost_cents", "quantity"])
    for sku in sorted(warehouse.items):
        item = warehouse.items[sku]
        writer.writerow([item.sku, item.name, item.unit_cost_cents, item.quantity])
    return out.getvalue()


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def markup_price(item: Item, margin: float) -> int:
    """The selling price in cents for a gross margin, e.g. 0.25 for 25 %."""
    if not 0 <= margin < 1:
        raise ValueError("margin must be at least 0 and below 1")
    return round(item.unit_cost_cents / (1 - margin))


def bulk_discount(quantity: int) -> float:
    """The fraction knocked off for buying in bulk."""
    if quantity >= 100:
        return 0.15
    if quantity >= 20:
        return 0.05
    return 0.0


def quote_price(item: Item, quantity: int, margin: float = 0.3) -> int:
    unit = markup_price(item, margin)
    return round(unit * quantity * (1 - bulk_discount(quantity)))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def stock_value(warehouse: Warehouse) -> int:
    return sum(item.value_cents for item in warehouse.items.values())


def low_stock(warehouse: Warehouse, threshold: int = 5) -> list[Item]:
    low = [item for item in warehouse.items.values() if item.quantity < threshold]
    return sorted(low, key=lambda item: (item.quantity, item.sku))


def movement_summary(warehouse: Warehouse) -> dict[str, dict[str, int]]:
    """Total units moved per SKU, split by reason."""
    summary: dict[str, dict[str, int]] = defaultdict(dict)
    for movement in warehouse.movements:
        by_reason = summary[movement.sku]
        by_reason[movement.reason] = by_reason.get(movement.reason, 0) + abs(movement.delta)
    return dict(summary)


def render_report(warehouse: Warehouse, threshold: int = 5) -> str:
    lines = [f"{len(warehouse.items)} SKUs, stock value {stock_value(warehouse) / 100:.2f}"]
    for item in low_stock(warehouse, threshold):
        lines.append(f"LOW {item.sku} {item.name}: {item.quantity} left")
    return "\n".join(lines)
