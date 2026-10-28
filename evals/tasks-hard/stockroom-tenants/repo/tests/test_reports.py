import json

import pytest
from conftest import stock_up
from stockroom.errors import DuplicateSku, InvalidInput
from stockroom.importer import import_products
from stockroom.reports import alerts_report, low_stock_report, movements_csv, valuation_report
from stockroom.snapshot import snapshot


def test_valuation_report(inv) -> None:
    stock_up(inv)
    rows = [line.split() for line in valuation_report(inv.db).splitlines()]
    assert rows == [
        ["sku", "on", "hand", "unit", "cost", "value"],
        ["MUG-01", "40", "4.25", "170.00"],
        ["KET-02", "5", "19.99", "99.95"],
        ["TEA-07", "0", "3.50", "0.00"],
        ["total", "269.95"],
    ]


def test_low_stock_report(inv) -> None:
    stock_up(inv)
    assert low_stock_report(inv.db) == "nothing is low\n"
    inv.ship("KET-02", 4)
    assert low_stock_report(inv.db) == "KET-02  Red kettle  on hand 1  reorder level 2  order 2\n"


def test_movements_csv(inv) -> None:
    stock_up(inv)
    inv.ship("MUG-01", 2, "web-1")
    assert movements_csv(inv.db, "MUG-01") == (
        "id,sku,kind,qty,ref,at\n"
        "MV-000001,MUG-01,receive,40,PO-1001,2026-03-01T09:00:00Z\n"
        "MV-000003,MUG-01,ship,-2,web-1,2026-03-01T09:02:00Z\n"
    )
    assert len(movements_csv(inv.db).splitlines()) == 4


def test_alerts_report(inv) -> None:
    stock_up(inv)
    assert alerts_report(inv.db) == "no alerts\n"
    inv.ship("KET-02", 3)
    assert alerts_report(inv.db) == "2026-03-01T09:03:00Z  KET-02  on hand 2 (reorder level 2)\n"


def test_snapshot_leaves_costs_out(inv) -> None:
    stock_up(inv)
    data = json.loads(json.dumps(snapshot(inv)))
    assert data["products"][0] == {
        "sku": "KET-02",
        "name": "Red kettle",
        "unit": "pcs",
        "on_hand": 5,
    }
    assert "cost" not in json.dumps(data)


def test_import_products(inv) -> None:
    result = import_products(
        inv,
        "sku,name,unit_cost,reorder_level,opening_stock\n"
        "MUG-01,Blue mug,4.25,10,40\n"
        "KET-02,Red kettle,19.99,,\n",
    )
    assert result.added == ["MUG-01", "KET-02"]
    assert [(p.sku, q) for p, q in inv.levels()] == [("KET-02", 0), ("MUG-01", 40)]
    assert inv.history()[0].ref == "opening stock"


def test_an_import_is_all_or_nothing(inv) -> None:
    inv.add_product("KET-02", "Red kettle", 1999)
    with pytest.raises(DuplicateSku):
        import_products(
            inv, "sku,name,unit_cost,opening_stock\nMUG-01,Blue mug,4.25,40\nKET-02,Kettle,1,\n"
        )
    with pytest.raises(InvalidInput, match="line 3"):
        import_products(inv, "sku,name,unit_cost\nMUG-01,Blue mug,4.25\nCUP-03,Cup,cheap\n")
    assert [p.sku for p in inv.all_products()] == ["KET-02"]
    assert inv.history() == []
    assert inv.search("mug") == []
