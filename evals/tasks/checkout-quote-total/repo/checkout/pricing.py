from decimal import Decimal

from checkout.catalog import PRODUCTS


def unit_price(sku: str, quantity: int) -> Decimal:
    product = PRODUCTS[sku]
    price = product.price
    for threshold in sorted(product.tiers):
        if quantity > threshold:
            price = product.tiers[threshold]
    return price


def line_amount(sku: str, quantity: int) -> Decimal:
    return unit_price(sku, quantity) * quantity
