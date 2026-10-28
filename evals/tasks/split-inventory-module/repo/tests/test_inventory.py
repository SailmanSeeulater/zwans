import pytest

from inventory import (
    InsufficientStock,
    Item,
    Warehouse,
    load_items,
    low_stock,
    quote_price,
    render_report,
)

CSV = "sku,name,unit_cost_cents,quantity\nab1,Mug,400,3\ncd2,Plate,250,40\n"


def test_load_and_report() -> None:
    warehouse = load_items(CSV)
    assert render_report(warehouse) == "2 SKUs, stock value 112.00\nLOW AB1 Mug: 3 left"


def test_shipping_too_much() -> None:
    warehouse = Warehouse()
    warehouse.add_item(Item("x1", "Bowl", 100, 2))
    with pytest.raises(InsufficientStock):
        warehouse.ship("x1", 3)


def test_quote_price_with_bulk_discount() -> None:
    assert quote_price(Item("x1", "Bowl", 700), 20) == 19000


def test_low_stock_order() -> None:
    warehouse = load_items(CSV + "ef3,Cup,100,1\n")
    assert [item.sku for item in low_stock(warehouse)] == ["EF3", "AB1"]
