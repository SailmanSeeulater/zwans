from decimal import Decimal

from checkout.catalog import PRODUCTS
from checkout.discounts import after_coupon, after_loyalty
from checkout.pricing import line_amount
from checkout.shipping import shipping_cost
from checkout.tax import cents, vat


def quote(
    lines: dict[str, int], tier: str = "bronze", country: str = "NL", coupon: str | None = None
) -> Decimal:
    """The total to charge, in euros including VAT and shipping."""
    net_goods = Decimal("0")
    total_vat = Decimal("0")
    for sku, quantity in lines.items():
        category = PRODUCTS[sku].category
        amount = line_amount(sku, quantity)
        amount = after_coupon(amount, category, coupon)
        amount = cents(after_loyalty(amount, tier, coupon))
        net_goods += amount
        total_vat += vat(amount, country, category)
    shipping = shipping_cost(net_goods, country)
    total_vat += vat(shipping, country, "goods")
    return net_goods + shipping + total_vat
