import json

from orderdesk import open_app
from orderdesk.cli import VIEWS
from orderdesk.commands import COMMANDS


def paid_order(cli, customer: str = "alice") -> str:
    """Place and pay a 30.00 order; returns its id."""
    code, out, _ = cli(
        "place",
        "--customer",
        customer,
        "--email",
        f"{customer}@example.com",
        "--line",
        "MUG-01:2:9.50",
        "--line",
        "TEA-07:1:11.00",
    )
    assert code == 0
    order_id = out.split()[-1]
    assert cli("pay", order_id, "--amount", "30.00")[0] == 0
    return order_id


def refund(
    cli, order_id: str, amount: str, reason: str = "lid cracked", role: str = "manager"
) -> int:
    return cli(
        "--actor", "mo", "--role", role, "refund", order_id, "--amount", amount, "--reason", reason
    )[0]


def status(cli, order_id: str) -> tuple[str, str]:
    """The status as `show` and as `list` see it."""
    shown = [line for line in cli("show", order_id)[1].splitlines() if line.startswith("status: ")]
    listed = [
        line.split()[2] for line in cli("list")[1].splitlines() if line.split()[0] == order_id
    ]
    return shown[0].removeprefix("status: "), listed[0]


def report(cli) -> list[list[str]]:
    code, out, _ = cli("--role", "manager", "report")
    assert code == 0
    return [line.split() for line in out.splitlines()[1:]]


def spent(cli, customer: str = "alice") -> str:
    for line in cli("--role", "manager", "customers")[1].splitlines():
        words = line.split()
        if words[0] == customer:
            return words[-1]
    raise AssertionError(f"{customer} is not in the customer figures")


def event_count(cli) -> int:
    return len((cli.data / "events.jsonl").read_text("utf-8").splitlines())


def test_refund_is_a_registered_command_with_a_cli(cli) -> None:
    assert "refund" in COMMANDS
    code, out, _ = cli("help")
    names = [line.split()[0] for line in out.splitlines() if line.startswith("  ")]
    assert "refund" in names
    assert sorted(names) == sorted([*COMMANDS, *VIEWS])


def test_a_partial_refund_on_a_shipped_order(cli) -> None:
    order_id = paid_order(cli)
    cli("ship", order_id, "--carrier", "PostNL", "--tracking", "3S123")
    assert refund(cli, order_id, "5.00") == 0
    assert status(cli, order_id) == ("shipped", "shipped")


def test_a_partly_refunded_paid_order_can_still_ship(cli) -> None:
    order_id = paid_order(cli)
    assert refund(cli, order_id, "12.50") == 0
    assert status(cli, order_id) == ("paid", "paid")
    assert cli("ship", order_id, "--carrier", "PostNL", "--tracking", "3S123")[0] == 0


def test_several_refunds_up_to_what_was_paid(cli) -> None:
    order_id = paid_order(cli)
    cli("ship", order_id, "--carrier", "PostNL", "--tracking", "3S123")
    assert refund(cli, order_id, "10.00") == 0
    assert refund(cli, order_id, "20.01") != 0
    assert refund(cli, order_id, "20.00") == 0
    assert status(cli, order_id) == ("refunded", "refunded")

    before = event_count(cli)
    assert refund(cli, order_id, "0.01") != 0
    assert event_count(cli) == before


def test_a_fully_refunded_unshipped_order_does_not_ship(cli) -> None:
    order_id = paid_order(cli)
    assert refund(cli, order_id, "30.00") == 0
    assert status(cli, order_id) == ("refunded", "refunded")
    assert cli("ship", order_id, "--carrier", "PostNL", "--tracking", "3S123")[0] != 0


def test_refunds_must_be_positive_and_have_a_reason(cli) -> None:
    order_id = paid_order(cli)
    before = event_count(cli)
    assert refund(cli, order_id, "30.01") != 0
    assert refund(cli, order_id, "0.00") != 0
    assert refund(cli, order_id, "5.00", reason="  ") != 0
    assert event_count(cli) == before


def test_only_paid_orders_can_be_refunded(cli) -> None:
    cli("place", "--customer", "bob", "--email", "bob@example.com", "--line", "MUG-01:1:9.50")
    assert refund(cli, "ORD-0001", "1.00") != 0

    cancelled = paid_order(cli)
    cli("--role", "manager", "cancel", cancelled, "--reason", "out of stock")
    before = event_count(cli)
    assert refund(cli, cancelled, "1.00") != 0
    assert event_count(cli) == before
    assert spent(cli) == "0.00"


def test_only_managers_refund(cli) -> None:
    order_id = paid_order(cli)
    assert refund(cli, order_id, "5.00", role="clerk") == 3
    assert refund(cli, order_id, "5.00", role="auditor") == 3
    assert refund(cli, order_id, "5.00", role="manager") == 0


def test_refunds_are_audited(cli) -> None:
    order_id = paid_order(cli)
    refund(cli, order_id, "5.00", role="clerk")
    refund(cli, order_id, "99.00")
    refund(cli, order_id, "5.00")

    app = open_app(cli.data)
    entries = [e for e in app.audit.entries() if e["command"] == "refund"]
    assert [(e["order_id"], e["outcome"]) for e in entries] == [
        (order_id, "denied"),
        (order_id, "rejected"),
        (order_id, "ok"),
    ]
    details = entries[-1]["details"]
    assert "lid cracked" in details.values()
    assert {500, "5.00", "5"} & {v for v in details.values() if isinstance(v, (int, str))}


def test_refunds_show_up_in_the_report_on_their_own_day(cli) -> None:
    order_id = paid_order(cli)
    cli.at("2026-03-02T15:00:00Z")
    assert refund(cli, order_id, "5.00") == 0

    assert report(cli) == [
        ["2026-03-01", "30.00", "0.00", "30.00"],
        ["2026-03-02", "0.00", "5.00", "-5.00"],
        ["total", "30.00", "5.00", "25.00"],
    ]
    assert spent(cli) == "25.00"


def test_cancelling_after_a_partial_refund_gives_back_only_the_rest(cli) -> None:
    order_id = paid_order(cli)
    cli.at("2026-03-02T15:00:00Z")
    assert refund(cli, order_id, "10.00") == 0
    cli.at("2026-03-03T09:00:00Z")
    assert cli("--role", "manager", "cancel", order_id, "--reason", "out of stock")[0] == 0

    assert report(cli) == [
        ["2026-03-01", "30.00", "0.00", "30.00"],
        ["2026-03-02", "0.00", "10.00", "-10.00"],
        ["2026-03-03", "0.00", "20.00", "-20.00"],
        ["total", "30.00", "30.00", "0.00"],
    ]
    assert spent(cli) == "0.00"
    cancel_mail = open_app(cli.data).outbox.messages()[-1]
    assert "refunded 20.00" in cancel_mail["body"]


def test_the_customer_is_told(cli) -> None:
    order_id = paid_order(cli)
    assert refund(cli, order_id, "5.00") == 0

    outbox = [
        json.loads(line) for line in (cli.data / "outbox.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(outbox) == 2
    mail = outbox[-1]
    text = mail["subject"] + "\n" + mail["body"]
    assert mail["to"] == "alice@example.com"
    assert "refund" in text.lower()
    assert "5.00" in text
    assert order_id in text
    assert "lid cracked" in text


def test_everything_is_rebuilt_from_the_log(cli) -> None:
    first = paid_order(cli, "alice")
    second = paid_order(cli, "bob")
    refund(cli, first, "30.00")
    refund(cli, second, "7.25")

    app = open_app(cli.data)
    assert app.desk.state(first).status == "refunded"
    assert app.desk.state(second).status == "paid"
    assert {row.order_id: row.status for row in app.orders.rows()} == {
        first: "refunded",
        second: "paid",
    }
    assert [r.order_id for r in app.orders.rows("refunded")] == [first]
    assert app.sales.total().refunds_cents == 3725
    assert {c.customer: c.spent_cents for c in app.customers.customers()} == {
        "alice": 0,
        "bob": 2275,
    }
    for row in app.orders.rows():
        assert row.status == app.desk.state(row.order_id).status
