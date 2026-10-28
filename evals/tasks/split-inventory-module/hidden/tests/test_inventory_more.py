import pytest

import inventory
import inventory.models
import inventory.pricing
import inventory.reports
import inventory.storage
from inventory.cli import main

PUBLIC = {
    "models": ["InsufficientStock", "Item", "StockMovement", "UnknownSku"],
    "storage": ["Warehouse", "dump_items", "load_items"],
    "pricing": ["bulk_discount", "markup_price", "quote_price"],
    "reports": ["low_stock", "movement_summary", "render_report", "stock_value"],
}
CSV = "sku,name,unit_cost_cents,quantity\nab1,Mug,400,3\ncd2,Plate,250,40\n"


def test_package_still_exports_everything() -> None:
    expected = sorted(name for names in PUBLIC.values() for name in names)
    assert sorted(inventory.__all__) == expected
    for module, names in PUBLIC.items():
        for name in names:
            assert getattr(inventory, name) is getattr(getattr(inventory, module), name)


def test_star_import() -> None:
    namespace: dict = {}
    exec("from inventory import *", namespace)
    assert namespace["Warehouse"] is inventory.storage.Warehouse


def test_movements_and_summary() -> None:
    warehouse = inventory.load_items(CSV)
    warehouse.receive("ab1", 10)
    warehouse.ship("AB1", 4)
    warehouse.ship("cd2", 40)
    assert warehouse.get("ab1").quantity == 9
    assert inventory.movement_summary(warehouse) == {
        "AB1": {"opening": 3, "received": 10, "shipped": 4},
        "CD2": {"opening": 40, "shipped": 40},
    }
    assert repr(warehouse.movements[-1]) == "StockMovement('CD2', -40, 'shipped')"


def test_errors() -> None:
    warehouse = inventory.Warehouse()
    with pytest.raises(inventory.UnknownSku) as caught:
        warehouse.get("zz")
    assert str(caught.value) == "unknown SKU 'ZZ'"
    assert isinstance(caught.value, KeyError)
    warehouse.add_item(inventory.Item("a", "A", 5, 1))
    with pytest.raises(inventory.InsufficientStock, match="A: wanted 2, only 1 on hand"):
        warehouse.ship("a", 2)
    with pytest.raises(ValueError):
        warehouse.add_item(inventory.Item("A", "Again", 5))
    with pytest.raises(ValueError):
        warehouse.receive("a", 0)


def test_round_trip() -> None:
    text = inventory.dump_items(inventory.load_items(CSV))
    assert text == "sku,name,unit_cost_cents,quantity\nAB1,Mug,400,3\nCD2,Plate,250,40\n"
    assert inventory.load_items(text).items == inventory.load_items(CSV).items


def test_pricing() -> None:
    item = inventory.Item("p", "Pan", 1000)
    assert inventory.markup_price(item, 0.2) == 1250
    assert inventory.bulk_discount(19) == 0.0
    assert inventory.bulk_discount(100) == 0.15
    assert inventory.quote_price(item, 100, margin=0.5) == 170000
    with pytest.raises(ValueError):
        inventory.markup_price(item, 1)


def test_reports() -> None:
    warehouse = inventory.load_items(CSV)
    assert inventory.stock_value(warehouse) == 11200
    assert inventory.low_stock(warehouse, threshold=50) == [
        inventory.Item("AB1", "Mug", 400, 3),
        inventory.Item("CD2", "Plate", 250, 40),
    ]


def test_cli(tmp_path, capsys) -> None:
    stock = tmp_path / "stock.csv"
    stock.write_text(CSV, encoding="utf-8")
    assert main([str(stock)]) == 0
    assert capsys.readouterr().out == "2 SKUs, stock value 112.00\nLOW AB1 Mug: 3 left\n"
