import pytest
from fulfil.billing import discount_for, goods_value, order_total
from fulfil.money import format_cents, round_half_up
from helpers import assert_consistent


def test_round_half_up() -> None:
    assert [round_half_up(n, 2) for n in (0, 1, 2, 3, 5)] == [0, 1, 1, 2, 3]
    assert round_half_up(449, 100) == 4
    assert round_half_up(450, 100) == 5
    with pytest.raises(ValueError):
        round_half_up(-1, 2)


def test_discounts_round_half_up_to_the_cent() -> None:
    assert discount_for(3950, 15) == 593  # 592.5
    assert discount_for(30, 15) == 5  # 4.5
    assert discount_for(10, 15) == 2  # 1.5
    assert goods_value(30, 15) == 25
    assert discount_for(1234, 0) == 0


def test_format_cents() -> None:
    assert (format_cents(3852), format_cents(5), format_cents(-120)) == ("38.52", "0.05", "-1.20")


def test_the_invoice_is_the_order_total(shop) -> None:
    order = shop.place_order("alice", {"CUP-03": 3, "MUG-01": 1}, coupon="SPRING15")
    invoice = shop.ship(order.id)
    assert invoice.total_cents == order_total(order) == 980 - 147 + 495
    assert_consistent(shop)


def test_shipping_is_never_discounted(shop) -> None:
    order = shop.place_order("alice", {"CUP-03": 1}, coupon="STAFF30")
    invoice = shop.ship(order.id)
    assert (invoice.subtotal_cents, invoice.discount_cents, invoice.shipping_cents) == (10, 3, 495)
    assert_consistent(shop)


def test_no_coupon_no_discount(shop) -> None:
    order = shop.place_order("alice", {"TEA-07": 2})
    assert shop.ship(order.id).total_cents == 2200 + 495
    assert_consistent(shop)
