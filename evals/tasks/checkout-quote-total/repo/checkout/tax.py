from decimal import ROUND_HALF_UP, Decimal

VAT = {
    "NL": {"food": Decimal("0.09"), "goods": Decimal("0.21")},
    "DE": {"food": Decimal("0.07"), "goods": Decimal("0.19")},
    "BE": {"food": Decimal("0.06"), "goods": Decimal("0.21")},
}

CENT = Decimal("0.01")


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def vat(amount: Decimal, country: str, category: str) -> Decimal:
    return cents(amount * VAT[country][category])
