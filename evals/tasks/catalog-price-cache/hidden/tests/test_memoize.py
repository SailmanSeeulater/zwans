from shop.cache import memoize
from shop.catalog import price


def make_counted():
    calls = []

    @memoize
    def scaled(value: int, factor: int = 1, offset: int = 0) -> int:
        calls.append((value, factor, offset))
        return value * factor + offset

    return scaled, calls


def test_keyword_arguments_are_part_of_the_key() -> None:
    scaled, _ = make_counted()

    assert scaled(2, factor=3) == 6
    assert scaled(2, factor=5) == 10
    assert scaled(2, offset=1) == 3
    assert scaled(2, factor=3, offset=1) == 7
    assert scaled(2) == 2


def test_mixed_positional_and_keyword() -> None:
    scaled, _ = make_counted()

    assert scaled(2, 3) == 6
    assert scaled(2, factor=4) == 8
    assert scaled(2, 3, offset=10) == 16
    assert scaled(2, 3) == 6


def test_repeated_calls_hit_the_cache() -> None:
    scaled, calls = make_counted()

    scaled(4, factor=2)
    scaled(4, factor=2)
    scaled(4, factor=2)
    scaled(7)
    scaled(7)

    assert calls == [(4, 2, 0), (7, 1, 0)]
    assert scaled.cache_stats() == {"hits": 3, "misses": 2}


def test_keyword_order_does_not_change_the_answer() -> None:
    scaled, _ = make_counted()

    assert scaled(1, factor=2, offset=3) == 5
    assert scaled(1, offset=3, factor=2) == 5
    assert scaled(1, offset=2, factor=3) == 5
    assert scaled(1, offset=0, factor=3) == 3


def test_cache_clear() -> None:
    scaled, calls = make_counted()

    scaled(3, factor=3)
    scaled.cache_clear()
    scaled(3, factor=3)

    assert len(calls) == 2
    assert scaled.cache_stats() == {"hits": 0, "misses": 1}


def test_catalog_prices_by_keyword() -> None:
    price.cache_clear()

    assert price("TSHIRT", currency="GBP") == 1896
    assert price("TSHIRT", currency="EUR") == 2208
    assert price("TSHIRT", currency="EUR", quantity=10) == 20976
    assert price("TSHIRT", quantity=10) == 22800
    assert price("TSHIRT") == 2400
    assert price.cache_stats()["misses"] == 5
    assert price("TSHIRT", currency="EUR") == 2208
    assert price.cache_stats()["hits"] == 1
