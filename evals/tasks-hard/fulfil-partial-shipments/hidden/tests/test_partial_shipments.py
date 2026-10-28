import pytest
from fulfil.billing import order_total
from fulfil.errors import FulfilError
from fulfil.reports import BacklogLine, backlog, sales
from helpers import assert_consistent, shipped


def contents(invoice) -> dict[str, int]:
    return {line.sku: line.qty for line in invoice.lines}


def test_ship_part_of_an_order_then_the_rest(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 2}, coupon="SPRING15")

    first = shop.ship(order.id, {"MUG-01": 1})
    assert contents(first) == {"MUG-01": 1}
    assert first.subtotal_cents == 950
    assert order.status == "partially_shipped"
    assert (shop.inventory.on_hand("MUG-01"), shop.inventory.reserved("MUG-01")) == (9, 2)
    assert shop.inventory.reserved("TEA-07") == 2
    assert_consistent(shop)

    second = shop.ship(order.id)
    assert contents(second) == {"MUG-01": 2, "TEA-07": 2}
    assert order.status == "shipped"
    assert sum(i.total_cents for i in shop.invoices_for(order.id)) == order_total(order)
    assert [i.number for i in shop.invoices_for(order.id)] == ["INV-00001", "INV-00002"]
    assert_consistent(shop)


def test_a_shipment_can_hold_several_lines(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 2, "CUP-03": 10})
    invoice = shop.ship(order.id, {"TEA-07": 2, "CUP-03": 4})
    assert contents(invoice) == {"TEA-07": 2, "CUP-03": 4}
    assert order.status == "partially_shipped"
    shop.ship(order.id, {"MUG-01": 3, "CUP-03": 6})
    assert order.status == "shipped"
    assert_consistent(shop)


def test_shipping_everything_at_once_still_works(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 1}, coupon="SPRING15")
    invoice = shop.ship(order.id, {"MUG-01": 3, "TEA-07": 1})
    assert order.status == "shipped"
    assert invoice.total_cents == order_total(order) == 3852
    assert_consistent(shop)


def test_shipping_is_charged_once(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3})
    for _ in range(3):
        shop.ship(order.id, {"MUG-01": 1})
    invoices = shop.invoices_for(order.id)
    assert len(invoices) == 3
    assert sum(i.shipping_cents for i in invoices) == 495
    assert sum(i.total_cents for i in invoices) == 3 * 950 + 495
    assert_consistent(shop)


def test_discounts_on_partial_invoices_add_up(shop) -> None:
    # 15% of 10 cents is 1.5 (rounds to 2); 15% of 30 cents is 4.5 (rounds to 5), not 6.
    order = shop.place_order("alice", {"CUP-03": 3}, coupon="SPRING15")
    shop.ship(order.id, {"CUP-03": 1})
    assert_consistent(shop)
    shop.ship(order.id, {"CUP-03": 1})
    assert_consistent(shop)
    shop.ship(order.id, {"CUP-03": 1})
    invoices = shop.invoices_for(order.id)
    assert sum(i.discount_cents for i in invoices) == 5
    assert sum(i.total_cents for i in invoices) == order_total(order) == 30 - 5 + 495
    assert_consistent(shop)


def test_odd_splits_with_a_discount(shop) -> None:
    order = shop.place_order("alice", {"CUP-03": 7, "MUG-01": 3, "TEA-07": 1}, coupon="STAFF30")
    for lines in (
        {"CUP-03": 1},
        {"CUP-03": 3, "MUG-01": 1},
        {"TEA-07": 1},
        {"CUP-03": 1, "MUG-01": 1},
    ):
        shop.ship(order.id, lines)
        assert_consistent(shop)
    shop.ship(order.id)
    assert sum(i.total_cents for i in shop.invoices_for(order.id)) == order_total(order)
    assert_consistent(shop)


def test_bad_shipments_are_refused_and_change_nothing(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 1})
    shop.ship(order.id, {"MUG-01": 2})
    for lines in (
        {"MUG-01": 2},
        {"CUP-03": 1},
        {"MUG-01": 0},
        {"TEA-07": -1},
        {"MUG-01": 1, "TEA-07": 2},
    ):
        with pytest.raises(FulfilError):
            shop.ship(order.id, lines)
        assert len(shop.invoices) == 1
        assert shipped(shop, order.id) == {"MUG-01": 2}
        assert (shop.inventory.on_hand("MUG-01"), shop.inventory.on_hand("TEA-07")) == (8, 10)
        assert_consistent(shop)
    shop.ship(order.id)
    with pytest.raises(FulfilError):
        shop.ship(order.id, {"MUG-01": 1})
    with pytest.raises(FulfilError):
        shop.ship(order.id)
    assert_consistent(shop)


def test_cancelling_a_partly_shipped_order_cancels_the_rest(shop) -> None:
    other = shop.place_order("bob", {"MUG-01": 4})
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 2}, coupon="WELCOME10")
    shop.ship(order.id, {"MUG-01": 1})
    invoiced = sum(i.total_cents for i in shop.invoices_for(order.id))

    shop.cancel(order.id)
    assert shop.inventory.reserved("MUG-01") == 4  # only bob's
    assert shop.inventory.reserved("TEA-07") == 0
    assert shop.inventory.available("MUG-01") == 10 - 1 - 4
    assert sum(i.total_cents for i in shop.invoices_for(order.id)) == invoiced
    assert_consistent(shop)

    with pytest.raises(FulfilError):
        shop.ship(order.id)
    with pytest.raises(FulfilError):
        shop.ship(order.id, {"TEA-07": 1})
    with pytest.raises(FulfilError):
        shop.cancel(order.id)
    shop.ship(other.id)
    assert_consistent(shop)


def test_only_what_shipped_can_come_back(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 1}, coupon="SPRING15")
    shop.ship(order.id, {"MUG-01": 2})
    with pytest.raises(FulfilError):
        shop.return_items(order.id, "MUG-01", 3)
    with pytest.raises(FulfilError):
        shop.return_items(order.id, "TEA-07", 1)
    shop.return_items(order.id, "MUG-01", 2)
    with pytest.raises(FulfilError):
        shop.return_items(order.id, "MUG-01", 1)
    assert_consistent(shop)

    shop.ship(order.id)
    shop.return_items(order.id, "MUG-01", 1)
    shop.return_items(order.id, "TEA-07", 1)
    assert shop.inventory.on_hand("MUG-01") == 10
    assert_consistent(shop)


def test_returns_after_cancelling_the_rest(shop) -> None:
    order = shop.place_order("alice", {"CUP-03": 5})
    shop.ship(order.id, {"CUP-03": 2})
    shop.cancel(order.id)
    with pytest.raises(FulfilError):
        shop.return_items(order.id, "CUP-03", 3)
    shop.return_items(order.id, "CUP-03", 2)
    assert_consistent(shop)


def test_sales_count_what_left_each_day(shop, clock) -> None:
    order = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 2})
    first = shop.ship(order.id, {"MUG-01": 2})
    clock.day = "2026-03-02"
    second = shop.ship(order.id)

    day1, day2 = sales(shop, "2026-03-01"), sales(shop, "2026-03-02")
    assert day1.units == {"MUG-01": 2}
    assert day1.invoiced_cents == first.total_cents
    assert day2.units == {"MUG-01": 1, "TEA-07": 2}
    assert day2.invoiced_cents == second.total_cents


def test_sales_count_partial_shipments_of_orders_that_never_complete(shop, clock) -> None:
    order = shop.place_order("alice", {"MUG-01": 3})
    shop.ship(order.id, {"MUG-01": 1})
    clock.day = "2026-03-02"
    shop.cancel(order.id)
    assert sales(shop, "2026-03-01").units == {"MUG-01": 1}
    assert sales(shop, "2026-03-02").units == {}


def test_the_backlog_shows_what_is_left(shop) -> None:
    first = shop.place_order("alice", {"MUG-01": 3, "TEA-07": 2})
    second = shop.place_order("bob", {"CUP-03": 5})
    third = shop.place_order("carol", {"MUG-01": 1, "CUP-03": 1})
    shop.ship(first.id, {"MUG-01": 3, "TEA-07": 1})
    shop.ship(second.id, {"CUP-03": 2})
    shop.ship(third.id, {"MUG-01": 1})
    shop.cancel(third.id)

    assert backlog(shop) == [
        BacklogLine(first.id, "alice", "TEA-07", 1),
        BacklogLine(second.id, "bob", "CUP-03", 3),
    ]
    shop.ship(first.id)
    shop.ship(second.id)
    assert backlog(shop) == []
    assert_consistent(shop)
