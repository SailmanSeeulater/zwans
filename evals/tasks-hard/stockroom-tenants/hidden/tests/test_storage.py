import json

import pytest
from conftest import Clock, stock_up
from stockroom import Database, Inventory
from stockroom.errors import CorruptDatabase, DuplicateSku, InsufficientStock


def test_everything_survives_reopening(tmp_path) -> None:
    path = tmp_path / "stock.json"
    first = Inventory(Database(path), clock=Clock())
    stock_up(first)
    first.ship("MUG-01", 31)

    again = Inventory(Database(path), clock=Clock())
    assert [(p.sku, q) for p, q in again.levels()] == [("KET-02", 5), ("MUG-01", 9), ("TEA-07", 0)]
    assert [p.sku for p in again.search("kettle")] == ["KET-02"]
    assert [a.sku for a in again.alerts()] == ["MUG-01"]
    assert again.receive("TEA-07", 1).id == "MV-000004"


def test_the_file_is_versioned_json(tmp_path) -> None:
    path = tmp_path / "stock.json"
    stock_up(Inventory(Database(path), clock=Clock()))
    data = json.loads(path.read_text("utf-8"))
    assert data["version"] == 1
    assert {"products", "movements", "alerts", "counters"} <= set(data)


def test_unreadable_files_are_refused(tmp_path) -> None:
    path = tmp_path / "stock.json"
    path.write_text("{nope", "utf-8")
    with pytest.raises(CorruptDatabase):
        Database(path)
    path.write_text('{"version": 99}', "utf-8")
    with pytest.raises(CorruptDatabase):
        Database(path)


def test_a_failed_change_leaves_nothing_behind(tmp_path, inv) -> None:
    stock_up(inv)
    with pytest.raises(InsufficientStock):
        inv.ship("KET-02", 50)
    with pytest.raises(DuplicateSku), inv.db.transaction():
        inv.add_product("CUP-03", "Paper cup", 10)
        inv.receive("CUP-03", 100)
        inv.add_product("MUG-01", "Duplicate", 1)
    assert [p.sku for p in inv.all_products()] == ["KET-02", "MUG-01", "TEA-07"]
    assert inv.search("cup") == []
    assert len(inv.history()) == 2
    assert inv.receive("TEA-07", 1).id == "MV-000003"


def test_rollback_clears_the_cache(inv) -> None:
    stock_up(inv)
    with pytest.raises(RuntimeError), inv.db.transaction():
        inv.rename("MUG-01", "Renamed")
        assert inv.product("MUG-01").name == "Renamed"
        raise RuntimeError("boom")
    assert inv.product("MUG-01").name == "Blue mug"
    assert [p.sku for p in inv.search("blue")] == ["MUG-01"]


def test_lookups_are_cached(inv) -> None:
    stock_up(inv)
    inv.product("MUG-01")
    hits = inv.db.cache.hits
    inv.product("MUG-01")
    assert inv.db.cache.hits == hits + 1


def test_a_database_from_stockroom_1_still_loads(legacy_file) -> None:
    inv = Inventory(Database(legacy_file), clock=Clock())
    assert [(p.sku, q) for p, q in inv.levels()] == [("KET-02", 2), ("MUG-01", 9), ("TEA-07", 118)]
    assert [p.sku for p in inv.search("green")] == ["TEA-07"]
    assert [a.sku for a in inv.alerts()] == ["MUG-01", "KET-02"]
    assert inv.valuation_cents() == 49123
    assert inv.receive("MUG-01", 1).id == "MV-000007"

    reopened = Inventory(Database(legacy_file), clock=Clock())
    assert reopened.on_hand("MUG-01") == 10
