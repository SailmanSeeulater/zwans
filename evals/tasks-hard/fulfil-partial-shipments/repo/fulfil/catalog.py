"""Products, prices and coupons."""

from dataclasses import dataclass

from .errors import InvalidRequest, UnknownProduct

# Coupon code -> percentage off the goods (never off shipping).
COUPONS: dict[str, int] = {
    "WELCOME10": 10,
    "SPRING15": 15,
    "STAFF30": 30,
}


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int


class Catalog:
    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def add(self, sku: str, name: str, price_cents: int) -> Product:
        if not sku or sku != sku.strip().upper():
            raise InvalidRequest(f"SKUs are upper case without spaces around them, not {sku!r}")
        if price_cents < 0:
            raise InvalidRequest("prices cannot be negative")
        if sku in self._products:
            raise InvalidRequest(f"{sku} is already in the catalog")
        product = Product(sku, name, price_cents)
        self._products[sku] = product
        return product

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownProduct(f"no product {sku}") from None

    def __contains__(self, sku: str) -> bool:
        return sku in self._products

    def skus(self) -> list[str]:
        return sorted(self._products)


def coupon_percent(code: str | None) -> int:
    if code is None:
        return 0
    try:
        return COUPONS[code.upper()]
    except KeyError:
        raise InvalidRequest(f"unknown coupon {code!r}") from None
