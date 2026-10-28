"""Product prices. Pricing a product walks several tables, so results are memoized."""

from shop.cache import memoize
from shop.rates import convert

BASE_PRICES = {  # US cents
    "MUG": 1250,
    "TSHIRT": 2400,
    "POSTER": 899,
}
BULK_QUANTITY = 10
BULK_DISCOUNT_PERCENT = 5


class UnknownProduct(Exception):
    pass


@memoize
def price(sku: str, currency: str = "USD", quantity: int = 1) -> int:
    """Total price of `quantity` items in the smallest unit of `currency`."""
    try:
        base = BASE_PRICES[sku]
    except KeyError:
        raise UnknownProduct(sku) from None
    total = convert(base, currency) * quantity
    if quantity >= BULK_QUANTITY:
        total -= total * BULK_DISCOUNT_PERCENT // 100
    return total


def set_base_price(sku: str, usd_cents: int) -> None:
    BASE_PRICES[sku] = usd_cents
    price.cache_clear()  # type: ignore[attr-defined]
