import pytest
from fulfil.errors import (
    FulfilError,
    InvalidRequest,
    InvalidState,
    OutOfStock,
    UnknownOrder,
    UnknownProduct,
)
from helpers import assert_consistent


def test_placing_an_order_reserves_its_stock(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 1})
    assert order.id == "SO-0001"
    assert order.status == "placed"
    assert [(line.sku, line.qty, line.unit_price_cents) for line in order.lines] == [
        ("MUG-01", 3, 950),
        ("TEA-07", 1, 1100),
    ]
    assert (
        shop.inventory.on_hand("MUG-01"),
        shop.inventory.reserved("MUG-01"),
        shop.inventory.available("MUG-01"),
    ) == (
        10,
        3,
        7,
    )
    assert_consistent(shop)


def test_an_order_needs_all_its_stock(shop) -> None:
    shop.place_order("alice", {"MUG-01": 8})
    with pytest.raises(OutOfStock):
        shop.place_order("bob", {"TEA-07": 1, "MUG-01": 3})
    assert shop.inventory.reserved("TEA-07") == 0
    assert len(shop.orders) == 1
    assert_consistent(shop)


def test_bad_orders_are_refused(shop) -> None:
    with pytest.raises(UnknownProduct):
        shop.place_order("alice", {"NOPE-1": 1})
    with pytest.raises(InvalidRequest):
        shop.place_order("alice", {"MUG-01": 0})
    with pytest.raises(InvalidRequest):
        shop.place_order("alice", {})
    with pytest.raises(InvalidRequest):
        shop.place_order("alice", {"MUG-01": 1}, coupon="FREESTUFF")
    assert shop.orders == {}
    assert_consistent(shop)


def test_shipping_takes_the_stock_and_invoices_the_order(shop, clock) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 1}, coupon="SPRING15")
    clock.day = "2026-03-02"
    invoice = shop.ship(order.id)

    assert order.status == "shipped"
    assert order.shipped_at.startswith("2026-03-02")
    assert [(line.sku, line.qty) for line in invoice.lines] == [("MUG-01", 3), ("TEA-07", 1)]
    assert (invoice.subtotal_cents, invoice.discount_cents, invoice.shipping_cents) == (
        3950,
        593,
        495,
    )
    assert invoice.total_cents == 3852
    assert invoice.number == "INV-00001"
    assert (shop.inventory.on_hand("MUG-01"), shop.inventory.reserved("MUG-01")) == (7, 0)
    assert_consistent(shop)


def test_an_order_ships_once(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 1})
    shop.ship(order.id)
    with pytest.raises(InvalidState):
        shop.ship(order.id)
    assert len(shop.invoices) == 1
    assert_consistent(shop)


def test_cancelling_releases_the_stock(shop) -> None:
    keep = shop.place_order("alice", {"MUG-01": 2})
    drop = shop.place_order("bob", {"MUG-01": 3, "TEA-07": 2})
    shop.cancel(drop.id)
    assert drop.status == "cancelled"
    assert shop.inventory.reserved("MUG-01") == 2
    assert shop.inventory.reserved("TEA-07") == 0
    assert shop.invoices_for(drop.id) == []
    with pytest.raises(InvalidState):
        shop.ship(drop.id)
    shop.ship(keep.id)
    with pytest.raises(InvalidState):
        shop.cancel(keep.id)
    assert_consistent(shop)


def test_unknown_orders(shop) -> None:
    for action in (shop.ship, shop.cancel, shop.order):
        with pytest.raises(UnknownOrder):
            action("SO-9999")
    assert issubclass(UnknownOrder, FulfilError)
