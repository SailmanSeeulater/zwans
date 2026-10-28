from fulfil.reports import BacklogLine, StockLine, backlog, sales, sales_text, stock
from helpers import assert_consistent


def test_sales_per_day(shop, clock) -> None:
    first = shop.place_order("alice", {"MUG-01": 2, "TEA-07": 1})
    second = shop.place_order("bob", {"MUG-01": 1})
    shop.ship(first.id)
    clock.day = "2026-03-02"
    shop.ship(second.id)
    shop.return_items(first.id, "TEA-07", 1)

    day1, day2 = sales(shop, "2026-03-01"), sales(shop, "2026-03-02")
    assert day1.units == {"MUG-01": 2, "TEA-07": 1}
    assert day1.invoiced_cents == 1900 + 1100 + 495
    assert day2.units == {"MUG-01": 1}
    assert (day2.invoiced_cents, day2.credited_cents, day2.net_cents) == (950 + 495, 1100, 345)
    assert sales(shop, "2026-03-03").units == {}
    assert_consistent(shop)


def test_sales_text(shop) -> None:
    shop.ship(shop.place_order("alice", {"MUG-01": 1}).id)
    assert sales_text(sales(shop, "2026-03-01")).splitlines() == [
        "sales 2026-03-01",
        "  MUG-01           1",
        "  invoiced       14.45",
        "  credited        0.00",
        "  net            14.45",
    ]


def test_the_backlog_is_what_still_has_to_ship(shop) -> None:
    first = shop.place_order("alice", {"MUG-01": 2, "TEA-07": 1})
    second = shop.place_order("bob", {"CUP-03": 5})
    third = shop.place_order("carol", {"MUG-01": 1})
    shop.ship(second.id)
    shop.cancel(third.id)
    assert backlog(shop) == [
        BacklogLine(first.id, "alice", "MUG-01", 2),
        BacklogLine(first.id, "alice", "TEA-07", 1),
    ]
    assert_consistent(shop)


def test_stock_report(shop) -> None:
    shop.place_order("alice", {"MUG-01": 2})
    assert stock(shop) == [
        StockLine("CUP-03", 100, 0, 100),
        StockLine("MUG-01", 10, 2, 8),
        StockLine("TEA-07", 10, 0, 10),
    ]
