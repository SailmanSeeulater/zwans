from decimal import Decimal

FREE_FROM = Decimal("75.00")  # net goods value, after discounts, before VAT
RATES = {"NL": Decimal("4.95"), "DE": Decimal("8.50"), "BE": Decimal("6.95")}


def shipping_cost(net_goods: Decimal, country: str) -> Decimal:
    if net_goods >= FREE_FROM:
        return Decimal("0.00")
    return RATES[country]
