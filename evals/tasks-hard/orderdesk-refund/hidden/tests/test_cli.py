import json

from orderdesk.cli import VIEWS
from orderdesk.commands import COMMANDS


def test_a_whole_order_through_the_cli(cli) -> None:
    assert cli(
        "place", "--customer", "alice", "--email", "alice@example.com", "--line", "MUG-01:2:9.50"
    ) == (
        0,
        "place: ORD-0001\n",
        "",
    )
    assert cli("pay", "ORD-0001", "--amount", "19.00")[0] == 0
    assert cli("ship", "ORD-0001", "--carrier", "PostNL", "--tracking", "3S123")[0] == 0

    code, out, _ = cli("show", "ORD-0001")
    assert code == 0
    assert "status: shipped" in out.splitlines()
    assert "paid: 19.00" in out.splitlines()

    code, out, _ = cli("list")
    assert out.split() == ["ORD-0001", "alice", "shipped", "19.00"]


def test_cli_errors_have_their_own_exit_codes(cli) -> None:
    cli("place", "--customer", "alice", "--email", "alice@example.com", "--line", "MUG-01:2:9.50")
    code, _, err = cli("cancel", "ORD-0001", "--reason", "duplicate")
    assert code == 3
    assert err.startswith("error: ")
    assert cli("pay", "ORD-0001", "--amount", "1.00")[0] == 4
    assert cli("pay", "ORD-0001", "--amount", "-1")[0] == 2
    assert cli("pay", "ORD-0404", "--amount", "1.00")[0] == 5
    assert cli("--role", "clerk", "report")[0] == 3


def test_the_report_and_customer_views(cli) -> None:
    cli("place", "--customer", "alice", "--email", "alice@example.com", "--line", "MUG-01:2:9.50")
    cli("pay", "ORD-0001", "--amount", "19.00")
    cli.at("2026-03-03T12:00:00Z")
    cli("--role", "manager", "cancel", "ORD-0001", "--reason", "out of stock")

    code, out, _ = cli("--role", "manager", "report")
    assert code == 0
    rows = [line.split() for line in out.splitlines()]
    assert rows == [
        ["day", "gross", "refunds", "net"],
        ["2026-03-01", "19.00", "0.00", "19.00"],
        ["2026-03-03", "0.00", "19.00", "-19.00"],
        ["total", "19.00", "19.00", "0.00"],
    ]
    code, out, _ = cli("--role", "auditor", "customers")
    assert out.split() == ["alice", "orders", "1", "spent", "0.00"]


def test_the_cli_keeps_the_audit_log_and_outbox(cli) -> None:
    cli("place", "--customer", "alice", "--email", "alice@example.com", "--line", "MUG-01:2:9.50")
    cli("--actor", "mo", "--role", "manager", "cancel", "ORD-0001", "--reason", "duplicate")

    code, out, _ = cli("--role", "auditor", "audit")
    assert [line.split()[1:5] for line in out.splitlines()] == [
        ["cli", "place", "ORD-0001", "ok"],
        ["mo", "cancel", "ORD-0001", "ok"],
    ]
    outbox = [
        json.loads(line) for line in (cli.data / "outbox.jsonl").read_text("utf-8").splitlines()
    ]
    assert [m["subject"] for m in outbox] == [
        "We got your order ORD-0001",
        "Your order ORD-0001 has been cancelled",
    ]


def test_help_lists_every_command_and_view(cli) -> None:
    code, out, _ = cli("help")
    names = [line.split()[0] for line in out.splitlines() if line.startswith("  ")]
    assert sorted(names) == sorted([*COMMANDS, *VIEWS])
    assert {"cancel", "note", "pay", "place", "ship", "show", "list", "report"} <= set(names)
