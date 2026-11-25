from conftest import sell

from shopdesk.reports import category_report, sales_report, stock_report, valuation


def sell_some_tees(shop) -> None:
    sell(shop, "Ann", ("TEE-S-RED", 2), ("TEE-M-BLUE", 1), ("MUG-01", 1))
    sell(shop, "Bob", ("TEE-M-RED", 3))
    sell(shop, "Cy", ("TEE-M-BLUE", 2))


def test_the_sales_report_rolls_variants_up_to_their_product(dressed) -> None:
    sell_some_tees(dressed)
    rows = sales_report(dressed)
    assert [(r.sku, r.name, r.units, r.revenue, r.orders) for r in rows] == [
        ("TEE-01", "Logo tee", 8, 3000 + 1700 + 4500 + 3400, 3),
        ("MUG-01", "Blue mug", 1, 1250, 1),
    ]


def test_the_sales_report_by_variant(dressed) -> None:
    sell_some_tees(dressed)
    rows = sales_report(dressed, by_variant=True)
    assert [(r.sku, r.name, r.units, r.revenue, r.orders) for r in rows] == [
        ("TEE-M-BLUE", "Logo tee (colour: blue, size: M)", 3, 5100, 2),
        ("TEE-M-RED", "Logo tee (colour: red, size: M)", 3, 4500, 1),
        ("TEE-S-RED", "Logo tee (colour: red, size: S)", 2, 3000, 1),
        ("MUG-01", "Blue mug", 1, 1250, 1),
    ]


def test_cancelled_orders_drop_out_of_both_views(dressed) -> None:
    sell_some_tees(dressed)
    dressed.cancel_order("SO-000003")
    assert [(r.sku, r.units) for r in sales_report(dressed)][0] == ("TEE-01", 6)
    assert "TEE-M-BLUE" in [r.sku for r in sales_report(dressed, by_variant=True)]
    assert [r.units for r in sales_report(dressed, by_variant=True) if r.sku == "TEE-M-BLUE"] == [1]


def test_the_category_report_goes_by_the_products_category(dressed) -> None:
    sell_some_tees(dressed)
    rows = {r.category: (r.units, r.revenue) for r in category_report(dressed)}
    assert rows == {"clothing": (8, 12600), "home": (1, 1250)}


def test_the_stock_report_has_a_row_per_variant(dressed) -> None:
    sell(dressed, "Ann", ("TEE-M-RED", 8))
    rows = {r.sku: r for r in stock_report(dressed)}
    assert "TEE-01" not in rows
    assert set(rows) == {"KET-02", "MUG-01", "TEA-07", "TEE-S-RED", "TEE-M-RED", "TEE-M-BLUE"}
    red = rows["TEE-M-RED"]
    assert (red.name, red.warehouses, red.total, red.reorder_level, red.low) == (
        "Logo tee (colour: red, size: M)", {"MAIN": 0, "WEST": 4}, 4, 5, True,
    )
    assert (rows["TEE-S-RED"].reorder_level, rows["TEE-S-RED"].low) == (3, False)
    assert [r.sku for r in stock_report(dressed, low_only=True)] == ["TEE-M-RED"]


def test_valuation_counts_every_variant_at_the_product_cost(dressed) -> None:
    rows, total = valuation(dressed)
    tee = [r for r in rows if r.sku == "TEE-01"]
    assert [(r.name, r.units, r.cost, r.value) for r in tee] == [("Logo tee", 28, 600, 16800)]
    assert not any(r.sku.startswith("TEE-") and r.sku != "TEE-01" for r in rows)
    assert total == 28600 + 16800
