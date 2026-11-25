from conftest import sell

from shopdesk.reports import category_report, daily_report, sales_report, stock_report, valuation


def test_sales_report_per_product_best_first(stocked) -> None:
    sell(stocked, "Ann", ("MUG-01", 2), ("TEA-07", 4))
    sell(stocked, "Bob", ("MUG-01", 1))
    rows = sales_report(stocked)
    assert [(r.sku, r.name, r.units, r.revenue, r.orders) for r in rows] == [
        ("MUG-01", "Blue mug", 3, 3750, 2),
        ("TEA-07", "Green tea, 100 g", 4, 1800, 1),
    ]


def test_sales_report_skips_cancelled_orders_and_counts_discounts(stocked) -> None:
    stocked.add_discount("HALF", "percent", 50, target_kind="product", target="KET-02")
    sell(stocked, "Ann", ("KET-02", 1), code="HALF")
    stocked.cancel_order(sell(stocked, "Bob", ("MUG-01", 5)))
    assert [(r.sku, r.revenue) for r in sales_report(stocked)] == [("KET-02", 1999)]


def test_sales_report_by_date(stocked) -> None:
    sell(stocked, "Ann", ("MUG-01", 1))
    stocked.clock.day = "2026-03-05"
    sell(stocked, "Bob", ("MUG-01", 2))
    assert [r.units for r in sales_report(stocked, start="2026-03-03")] == [2]
    assert [r.units for r in sales_report(stocked, end="2026-03-02")] == [1]
    days = daily_report(stocked)
    assert [(d.day, d.orders, d.units, d.revenue) for d in days] == [
        ("2026-03-02", 1, 1, 1250),
        ("2026-03-05", 1, 2, 2500),
    ]


def test_category_report_rolls_up_to_top_level(stocked) -> None:
    stocked.add_product("SPOON", "Spoon", 100)
    stocked.receive("SPOON", "MAIN", 5)
    sell(stocked, "Ann", ("MUG-01", 1), ("KET-02", 1), ("TEA-07", 2), ("SPOON", 3))
    rows = category_report(stocked)
    assert [(r.category, r.name, r.units, r.revenue) for r in rows] == [
        ("home", "Home", 2, 5249),
        ("pantry", "Pantry", 2, 900),
        ("(none)", "(none)", 3, 300),
    ]


def test_stock_report(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 4))
    rows = {r.sku: r for r in stock_report(stocked)}
    assert rows["MUG-01"].warehouses == {"MAIN": 20, "WEST": 5}
    assert (rows["KET-02"].total, rows["KET-02"].low) == (2, True)
    assert [r.sku for r in stock_report(stocked, low_only=True)] == ["KET-02"]


def test_valuation_at_cost(stocked) -> None:
    rows, total = valuation(stocked)
    assert [(r.sku, r.units, r.value) for r in rows] == [
        ("KET-02", 6, 12600),
        ("MUG-01", 25, 10000),
        ("TEA-07", 40, 6000),
    ]
    assert total == 28600
