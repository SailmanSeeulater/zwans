"""Coupons work per line; loyalty discounts come after them, also per line."""

from decimal import Decimal

COUPONS = {
    # code: (category it applies to, or None for every line; fraction off)
    "SPRING10": ("goods", Decimal("0.10")),
    "TEATIME": ("food", Decimal("0.15")),
    "ALL5": (None, Decimal("0.05")),
}

LOYALTY = {"bronze": Decimal("0"), "silver": Decimal("0.02"), "gold": Decimal("0.05")}


def after_coupon(amount: Decimal, category: str, coupon: str | None) -> Decimal:
    if coupon is None:
        return amount
    applies_to, off = COUPONS[coupon]
    if applies_to is not None and applies_to != category:
        return amount
    return amount * (1 - off)


def after_loyalty(amount: Decimal, tier: str, coupon: str | None) -> Decimal:
    # Loyalty does not stack with the store-wide coupon.
    if coupon == "ALL5":
        return amount
    return amount * (1 - LOYALTY[tier])
