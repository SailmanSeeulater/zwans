from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Product:
    name: str
    price: Decimal
    category: str  # "food" or "goods"; VAT and some coupons depend on it
    # Volume pricing: buying at least `quantity` units makes every unit cost `price`.
    tiers: dict[int, Decimal] = field(default_factory=dict)


PRODUCTS = {
    "TEA-01": Product("Green tea, 100 g", Decimal("4.95"), "food", {5: Decimal("4.60")}),
    "MUG-02": Product(
        "Stoneware mug", Decimal("7.50"), "goods", {6: Decimal("6.90"), 12: Decimal("6.40")}
    ),
    "POT-03": Product("Teapot", Decimal("24.00"), "goods"),
    "HON-04": Product("Honey, 250 g", Decimal("6.25"), "food", {10: Decimal("5.80")}),
}
