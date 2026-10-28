from decimal import Decimal

from checkout.quote import quote


def test_single_teapot_in_the_netherlands() -> None:
    # 24.00 + 4.95 shipping, plus 21 % VAT on both
    assert quote({"POT-03": 1}) == Decimal("35.03")
