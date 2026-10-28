from conftest import CLERK, MANAGER, place, place_and_pay
from orderdesk import open_app
from orderdesk.handlers.cancel import CancelOrder
from orderdesk.handlers.note import AddNote
from orderdesk.handlers.ship import ShipOrder


def test_customers_hear_about_their_order(app) -> None:
    order_id = place_and_pay(app)
    app.desk.execute(ShipOrder(order_id, "PostNL", "3S123"), CLERK)

    messages = app.outbox.messages()
    assert [m["to"] for m in messages] == ["alice@example.com"] * 2
    assert messages[0]["subject"] == f"We got your order {order_id}"
    assert "30.00" in messages[0]["body"]
    assert "3S123" in messages[1]["body"]


def test_a_cancellation_mentions_the_refund(app) -> None:
    paid = place_and_pay(app)
    app.desk.execute(CancelOrder(paid, "out of stock"), MANAGER)
    unpaid = place(app, "bob")
    app.desk.execute(CancelOrder(unpaid, "duplicate"), MANAGER)

    paid_mail, unpaid_mail = app.outbox.messages()[-3], app.outbox.messages()[-1]
    assert paid_mail["subject"] == f"Your order {paid} has been cancelled"
    assert "refunded 30.00" in paid_mail["body"]
    assert "out of stock" in paid_mail["body"]
    assert unpaid_mail["to"] == "bob@example.com"
    assert "refunded" not in unpaid_mail["body"]


def test_notes_are_not_sent_to_customers(app) -> None:
    order_id = place(app)
    app.desk.execute(AddNote(order_id, "customer is rude"), CLERK)
    assert len(app.outbox.messages()) == 1


def test_emails_are_not_sent_again_when_the_app_reopens(tmp_path, clock) -> None:
    first = open_app(tmp_path, clock=clock)
    place_and_pay(first)
    assert len(first.outbox.messages()) == 1

    second = open_app(tmp_path, clock=clock)
    assert len(second.outbox.messages()) == 1
