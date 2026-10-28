"""Selling prices."""

from inventory.models import Item


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
