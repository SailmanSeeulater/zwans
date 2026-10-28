from conftest import CLERK, MANAGER, place, place_and_pay
from orderdesk import open_app
from orderdesk.handlers.cancel import CancelOrder
from orderdesk.handlers.ship import ShipOrder


def test_the_order_list_follows_each_order(app) -> None:
    placed = place(app, "alice")
    shipped = place_and_pay(app, "bob")
    app.desk.execute(ShipOrder(shipped, "DHL", "JD1"), CLERK)
    cancelled = place_and_pay(app, "carol")
    app.desk.execute(CancelOrder(cancelled, "out of stock"), MANAGER)

    rows = {row.order_id: row.status for row in app.orders.rows()}
    assert rows == {placed: "placed", shipped: "shipped", cancelled: "cancelled"}
    assert [row.order_id for row in app.orders.rows("shipped")] == [shipped]


def test_the_order_list_agrees_with_the_aggregate(app) -> None:
    for customer in ("alice", "bob"):
        place_and_pay(app, customer)
    app.desk.execute(CancelOrder("ORD-0002", "fraud"), MANAGER)
    for row in app.orders.rows():
        assert row.status == app.desk.state(row.order_id).status


def test_the_sales_report_counts_refunds_on_the_day_they_happen(app, clock) -> None:
    clock.at = "2026-03-01T10:00:00Z"
    first = place_and_pay(app)
    place_and_pay(app, "bob")
    clock.at = "2026-03-02T08:00:00Z"
    app.desk.execute(CancelOrder(first, "out of stock"), MANAGER)

    days = [(d.day, d.gross_cents, d.refunds_cents, d.net_cents) for d in app.sales.days()]
    assert days == [("2026-03-01", 6000, 0, 6000), ("2026-03-02", 0, 3000, -3000)]
    total = app.sales.total()
    assert (total.gross_cents, total.refunds_cents, total.net_cents) == (6000, 3000, 3000)


def test_customer_figures_take_refunds_off(app) -> None:
    place_and_pay(app, "alice")
    second = place_and_pay(app, "alice")
    place(app, "bob")
    app.desk.execute(CancelOrder(second, "duplicate"), MANAGER)

    figures = {c.customer: (c.orders, c.spent_cents) for c in app.customers.customers()}
    assert figures == {"alice": (2, 3000), "bob": (1, 0)}


def test_read_models_are_rebuilt_from_the_log(tmp_path, clock) -> None:
    first = open_app(tmp_path, clock=clock)
    order_id = place_and_pay(first)
    first.desk.execute(CancelOrder(order_id, "duplicate"), MANAGER)

    second = open_app(tmp_path, clock=clock)
    assert [row.status for row in second.orders.rows()] == ["cancelled"]
    assert second.sales.total().net_cents == 0
    assert [c.spent_cents for c in second.customers.customers()] == [0]
