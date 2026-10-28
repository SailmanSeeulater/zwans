import pytest

from shop.catalog import UnknownProduct, price, set_base_price


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    price.cache_clear()


def test_price_in_dollars() -> None:
    assert price("TSHIRT") == 2400


def test_unknown_product() -> None:
    with pytest.raises(UnknownProduct):
        price("HAT")


def test_new_base_price_takes_effect() -> None:
    assert price("POSTER") == 899
    set_base_price("POSTER", 999)
    try:
        assert price("POSTER") == 999
    finally:
        set_base_price("POSTER", 899)
