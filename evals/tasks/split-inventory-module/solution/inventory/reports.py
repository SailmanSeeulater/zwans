"""Summaries of what is in the warehouse."""

from collections import defaultdict

from inventory.models import Item
from inventory.storage import Warehouse


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
