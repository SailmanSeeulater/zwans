"""The stock itself, and CSV import and export."""

import csv
import io

from inventory.models import InsufficientStock, Item, StockMovement, UnknownSku


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
