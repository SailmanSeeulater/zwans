import pytest
from conftest import CLERK, MANAGER, place, place_and_pay
from orderdesk.aggregate import replay
from orderdesk.errors import InvalidState, NotFound, ValidationError
from orderdesk.events import Line, OrderCancelled
from orderdesk.handlers.cancel import CancelOrder
from orderdesk.handlers.note import AddNote
from orderdesk.handlers.pay import PayOrder
from orderdesk.handlers.place import PlaceOrder
from orderdesk.handlers.ship import ShipOrder


def test_an_order_goes_from_placed_to_shipped(app) -> None:
    order_id = place(app)
    assert app.desk.state(order_id).status == "placed"
    assert app.desk.state(order_id).total_cents == 3000

    app.desk.execute(PayOrder(order_id, 3000, "card"), CLERK)
    assert app.desk.state(order_id).status == "paid"

    app.desk.execute(ShipOrder(order_id, "PostNL", "3S123"), CLERK)
    state = app.desk.state(order_id)
    assert (state.status, state.carrier, state.tracking) == ("shipped", "PostNL", "3S123")
    assert state.version == 3


def test_order_ids_count_up(app) -> None:
    assert place(app) == "ORD-0001"
    assert place(app) == "ORD-0002"


def test_payment_must_be_in_full(app) -> None:
    order_id = place(app)
    with pytest.raises(InvalidState):
        app.desk.execute(PayOrder(order_id, 1000, "card"), CLERK)
    with pytest.raises(ValidationError):
        app.desk.execute(PayOrder(order_id, 0, "card"), CLERK)
    with pytest.raises(ValidationError):
        app.desk.execute(PayOrder(order_id, 3000, "bitcoin"), CLERK)


def test_only_paid_orders_ship(app) -> None:
    order_id = place(app)
    with pytest.raises(InvalidState):
        app.desk.execute(ShipOrder(order_id, "PostNL", "3S123"), CLERK)


def test_cancelling_a_paid_order_gives_the_money_back(app) -> None:
    order_id = place_and_pay(app)
    events = app.desk.execute(CancelOrder(order_id, "customer changed their mind"), MANAGER)
    assert events == [
        OrderCancelled(order_id, "2026-03-01T09:00:00Z", "customer changed their mind", 3000)
    ]
    assert app.desk.state(order_id).status == "cancelled"


def test_cancelling_an_unpaid_order_refunds_nothing(app) -> None:
    order_id = place(app)
    [ev] = app.desk.execute(CancelOrder(order_id, "duplicate"), MANAGER)
    assert ev.refund_cents == 0


def test_shipped_or_cancelled_orders_cannot_be_cancelled(app) -> None:
    shipped = place_and_pay(app)
    app.desk.execute(ShipOrder(shipped, "PostNL", "3S123"), CLERK)
    with pytest.raises(InvalidState):
        app.desk.execute(CancelOrder(shipped, "too late"), MANAGER)

    cancelled = place(app)
    app.desk.execute(CancelOrder(cancelled, "duplicate"), MANAGER)
    with pytest.raises(InvalidState):
        app.desk.execute(CancelOrder(cancelled, "again"), MANAGER)


def test_cancel_needs_a_reason(app) -> None:
    order_id = place(app)
    with pytest.raises(ValidationError):
        app.desk.execute(CancelOrder(order_id, "  "), MANAGER)


def test_notes_record_the_author(app) -> None:
    order_id = place(app)
    app.desk.execute(AddNote(order_id, "gift wrap please"), CLERK)
    assert app.desk.state(order_id).notes == ["carla: gift wrap please"]


def test_commands_on_unknown_orders(app) -> None:
    with pytest.raises(NotFound):
        app.desk.execute(PayOrder("ORD-9999", 100, "card"), CLERK)
    with pytest.raises(NotFound):
        app.desk.state("ORD-9999")


def test_an_order_cannot_be_placed_twice(app) -> None:
    order_id = place(app)
    with pytest.raises(InvalidState):
        app.desk.execute(
            PlaceOrder(order_id, "bob", "bob@example.com", (Line("X", 1, 100),)), CLERK
        )


def test_place_validates_its_lines(app) -> None:
    with pytest.raises(ValidationError):
        app.desk.execute(PlaceOrder("ORD-0001", "bob", "bob@example.com", ()), CLERK)
    with pytest.raises(ValidationError):
        app.desk.execute(
            PlaceOrder("ORD-0001", "bob", "bob@example.com", (Line("X", 0, 100),)), CLERK
        )
    with pytest.raises(ValidationError):
        app.desk.execute(
            PlaceOrder("ORD-0001", "bob", "bob-at-example", (Line("X", 1, 100),)), CLERK
        )


def test_state_is_rebuilt_from_events_alone(app) -> None:
    order_id = place_and_pay(app)
    app.desk.execute(ShipOrder(order_id, "DHL", "JD0001"), CLERK)
    rebuilt = replay(order_id, app.store.load(order_id))
    assert rebuilt == app.desk.state(order_id)
