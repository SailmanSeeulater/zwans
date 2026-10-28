import pytest
from fulfil.errors import InvalidRequest, InvalidState
from helpers import assert_consistent


def test_returned_goods_are_restocked_and_credited(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 3}, coupon="WELCOME10")
    shop.ship(order.id)
    note = shop.return_items(order.id, "MUG-01", 1)
    assert (note.sku, note.qty, note.amount_cents) == ("MUG-01", 1, 855)
    assert note.number == "CN-00001"
    assert shop.inventory.on_hand("MUG-01") == 8
    assert shop.returned(order.id, "MUG-01") == 1
    assert_consistent(shop)


def test_credits_add_up_whatever_the_rounding(shop) -> None:
    order = shop.place_order("alice", {"CUP-03": 3}, coupon="SPRING15")
    shop.ship(order.id)
    amounts = [shop.return_items(order.id, "CUP-03", 1).amount_cents for _ in range(3)]
    assert sum(amounts) == 30 - 5
    assert_consistent(shop)


def test_each_unit_comes_back_once(shop) -> None:
    order = shop.place_order("alice", {"MUG-01": 2, "TEA-07": 1})
    shop.ship(order.id)
    shop.return_items(order.id, "MUG-01", 2)
    with pytest.raises(InvalidRequest):
        shop.return_items(order.id, "MUG-01", 1)
    with pytest.raises(InvalidRequest):
        shop.return_items(order.id, "TEA-07", 2)
    with pytest.raises(InvalidRequest):
        shop.return_items(order.id, "CUP-03", 1)
    with pytest.raises(InvalidRequest):
        shop.return_items(order.id, "TEA-07", 0)
    assert_consistent(shop)


def test_unshipped_goods_cannot_come_back(shop) -> None:
    placed = shop.place_order("alice", {"MUG-01": 2})
    with pytest.raises(InvalidState):
        shop.return_items(placed.id, "MUG-01", 1)
    cancelled = shop.place_order("bob", {"MUG-01": 1})
    shop.cancel(cancelled.id)
    with pytest.raises(InvalidState):
        shop.return_items(cancelled.id, "MUG-01", 1)
    assert shop.credit_notes == []
    assert_consistent(shop)
