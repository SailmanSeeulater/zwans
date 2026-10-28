import pytest
from conftest import stock_up
from stockroom.errors import DuplicateSku, InsufficientStock, InvalidInput, ProductInUse, UnknownSku
from stockroom.models import Alert, Product


def test_products_are_added_and_looked_up(inv) -> None:
    product = inv.add_product(" mug-01 ", "Blue   mug", 425, reorder_level=10)
    assert product == Product("MUG-01", "Blue mug", 425, 10, "pcs")
    assert inv.product("MUG-01") == product
    assert inv.all_products() == [product]


def test_skus_are_unique(inv) -> None:
    inv.add_product("MUG-01", "Blue mug", 425)
    with pytest.raises(DuplicateSku):
        inv.add_product("mug-01", "Another mug", 500)


def test_invalid_products_are_refused(inv) -> None:
    for sku, name, cost in (
        ("M", "Too short", 1),
        ("MUG 01", "Space", 1),
        ("MUG-01", "  ", 1),
        ("MUG-01", "Mug", -1),
    ):
        with pytest.raises(InvalidInput):
            inv.add_product(sku, name, cost)
    assert inv.all_products() == []


def test_unknown_skus(inv) -> None:
    with pytest.raises(UnknownSku):
        inv.product("NOPE-1")
    with pytest.raises(UnknownSku):
        inv.receive("NOPE-1", 1)
    with pytest.raises(UnknownSku):
        inv.on_hand("NOPE-1")


def test_stock_is_the_sum_of_movements(inv) -> None:
    stock_up(inv)
    inv.ship("MUG-01", 3, "web-1")
    inv.ship("MUG-01", 2, "web-2")
    assert inv.on_hand("MUG-01") == 35
    assert [(m.kind, m.qty, m.ref) for m in inv.history("MUG-01")] == [
        ("receive", 40, "PO-1001"),
        ("ship", -3, "web-1"),
        ("ship", -2, "web-2"),
    ]
    assert [p.sku for p, _ in inv.levels()] == ["KET-02", "MUG-01", "TEA-07"]
    assert dict((p.sku, q) for p, q in inv.levels()) == {"KET-02": 5, "MUG-01": 35, "TEA-07": 0}


def test_movement_ids_count_up(inv) -> None:
    stock_up(inv)
    assert [m.id for m in inv.history()] == ["MV-000001", "MV-000002"]


def test_cannot_ship_what_is_not_there(inv) -> None:
    stock_up(inv)
    with pytest.raises(InsufficientStock):
        inv.ship("KET-02", 6)
    assert inv.on_hand("KET-02") == 5
    assert len(inv.history("KET-02")) == 1


def test_quantities_must_be_positive(inv) -> None:
    stock_up(inv)
    with pytest.raises(InvalidInput):
        inv.receive("MUG-01", 0)
    with pytest.raises(InvalidInput):
        inv.ship("MUG-01", -1)


def test_a_count_adjusts_stock_to_what_was_counted(inv) -> None:
    stock_up(inv)
    movement = inv.count("MUG-01", 37)
    assert (movement.kind, movement.qty, movement.ref) == ("adjust", -3, "stocktake")
    assert inv.on_hand("MUG-01") == 37
    assert inv.count("MUG-01", 37) is None


def test_crossing_the_reorder_level_raises_one_alert(inv) -> None:
    stock_up(inv)
    inv.ship("MUG-01", 29)  # 11 left: not yet
    assert inv.alerts() == []
    inv.ship("MUG-01", 1)  # 10 left: at the level
    inv.ship("MUG-01", 1)  # 9 left: still low, no second alert
    assert [(a.sku, a.on_hand, a.reorder_level) for a in inv.alerts()] == [("MUG-01", 10, 10)]
    assert isinstance(inv.alerts()[0], Alert)

    inv.receive("MUG-01", 20)
    inv.count("MUG-01", 4)
    assert [(a.sku, a.on_hand) for a in inv.alerts()] == [("MUG-01", 10), ("MUG-01", 4)]


def test_low_stock_and_valuation(inv) -> None:
    stock_up(inv)
    inv.ship("KET-02", 4)
    assert [(p.sku, q) for p, q in inv.low_stock()] == [("KET-02", 1)]
    assert inv.valuation_cents() == 40 * 425 + 1 * 1999


def test_product_changes(inv) -> None:
    stock_up(inv)
    inv.rename("MUG-01", "Navy mug")
    inv.set_cost("MUG-01", 450)
    inv.set_reorder_level("MUG-01", 5)
    assert inv.product("MUG-01") == Product("MUG-01", "Navy mug", 450, 5)


def test_only_products_without_history_can_be_removed(inv) -> None:
    stock_up(inv)
    with pytest.raises(ProductInUse):
        inv.remove_product("MUG-01")
    inv.remove_product("TEA-07")
    with pytest.raises(UnknownSku):
        inv.product("TEA-07")
    assert inv.search("tea") == []


def test_search_by_name_or_sku(inv) -> None:
    stock_up(inv)
    assert [p.sku for p in inv.search("mug")] == ["MUG-01"]
    assert [p.sku for p in inv.search("RED KET")] == ["KET-02"]
    assert [p.sku for p in inv.search("tea-07")] == ["TEA-07"]
    assert inv.search("blue kettle") == []
    inv.rename("MUG-01", "Navy cup")
    assert inv.search("blue") == []
    assert [p.name for p in inv.search("navy")] == ["Navy cup"]
