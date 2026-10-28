import pytest

from shop.catalog import price
from shop.views import format_money, price_tag


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    price.cache_clear()


def test_format_money() -> None:
    assert format_money(123456, "USD") == "$1,234.56"
    assert format_money(5, "EUR") == "€0.05"
    assert format_money(1891, "JPY") == "¥1,891"


def test_price_tag_in_dollars() -> None:
    assert price_tag("MUG") == "$12.50"


def test_switching_currency() -> None:
    assert price_tag("MUG", "USD") == "$12.50"
    assert price_tag("MUG", "EUR") == "€11.50"
    assert price_tag("MUG", "JPY") == "¥1,891"


def test_bulk_price_tag() -> None:
    assert price_tag("POSTER", quantity=2) == "$17.98 for 2"
    assert price_tag("POSTER", quantity=10) == "$85.41 for 10"
