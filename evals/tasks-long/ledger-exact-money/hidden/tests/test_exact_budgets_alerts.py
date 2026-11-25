"""Budgets and the alerts they (and large transactions) send."""

import json
from pathlib import Path

import pytest
from conftest import exact

from billfold import Book


def test_budget_lines_are_exact(pennies: Book) -> None:
    pennies.budgets.set("Food", "2026-03", "0.40")
    pennies.budgets.set("Subscriptions", "2026-03", "19.99")
    lines = {line.category: line for line in pennies.budgets.status("2026-03")}
    exact(lines["Food"].budgeted, "0.40")
    exact(lines["Food"].spent, "0.30")
    exact(lines["Food"].remaining, "0.10")
    exact(lines["Subscriptions"].remaining, "0.00")
    assert not lines["Subscriptions"].over


def test_rollover_is_exact(book: Book) -> None:
    book.add_account("Checking")
    book.budgets.set("Fun", "2026-02", "10.10", rollover=True)
    for _ in range(3):
        book.add_transaction("Checking", "2026-02-10", "-0.10", category="Fun")
    book.budgets.set("Fun", "2026-03", "5.00")
    line = book.budgets.line("Fun", "2026-03")
    exact(line.carried, "9.80")
    exact(line.available, "14.80")


def test_budgets_refuse_floats(book: Book) -> None:
    with pytest.raises(TypeError):
        book.budgets.set("Food", "2026-03", 19.99)


def test_allocate_hands_leftover_cents_to_the_first_of_equal_remainders(book: Book) -> None:
    shares = book.budgets.allocate("100.00", {"Rent": 1, "Food": 1, "Fun": 1}, "2026-04")
    assert [str(shares[name]) for name in ("Rent", "Food", "Fun")] == ["33.34", "33.33", "33.33"]
    exact(book.budgets.get("Fun", "2026-04").amount, "33.33")


def test_allocate_uses_largest_remainders(book: Book) -> None:
    shares = book.budgets.allocate("1.00", {"Small": "1", "Large": "2"}, "2026-04")
    assert [str(shares["Small"]), str(shares["Large"])] == ["0.33", "0.67"]
    shares = book.budgets.allocate("0.05", {"A": 1, "B": 1, "C": 1, "D": 1}, "2026-05")
    assert [str(v) for v in shares.values()] == ["0.02", "0.01", "0.01", "0.01"]
    shares = book.budgets.allocate("2000.00", {"Food": 3, "Rent": 10, "Fun": 1}, "2026-06")
    assert [str(v) for v in shares.values()] == ["428.57", "1428.57", "142.86"]
    assert sum(shares.values()) == 2000


def test_budget_alert_carries_amounts_as_strings(pennies: Book) -> None:
    events = []
    pennies.on_alert(events.append)
    pennies.budgets.set("Food", "2026-03", "0.30")
    pennies.add_transaction("Checking", "2026-03-10", "-0.01", category="Food")
    (event,) = events
    assert event["type"] == "budget.exceeded"
    assert (event["budget"], event["spent"], event["over_by"]) == ("0.30", "0.31", "0.01")


def test_large_transaction_alert_is_exact(book: Book) -> None:
    events = []
    book.on_alert(events.append)
    book.add_account("Checking")
    book.set_large_transaction_alert("999.99")
    book.add_transaction("Checking", "2026-03-02", "-999.98", payee="TV")
    book.add_transaction("Checking", "2026-03-02", "-999.99", payee="Sofa")
    assert [e["payee"] for e in events] == ["Sofa"]
    assert (events[0]["amount"], events[0]["threshold"]) == ("-999.99", "999.99")


def test_cli_alerts_file_has_strings(cli) -> None:
    cli("account", "add", "Checking")
    cli("budget", "set", "Food", "2026-03", "0.30")
    cli("add", "Checking", "-0.10", "--category", "Food", "--date", "2026-03-02")
    cli("add", "Checking", "-0.20", "--category", "Food", "--date", "2026-03-02")
    code, _, err = cli("add", "Checking", "-0.01", "--category", "Food", "--date", "2026-03-02")
    assert code == 0 and "over budget" in err and "0.01" in err
    lines = (Path(cli.path).parent / "alerts.jsonl").read_text("utf-8").splitlines()
    event = json.loads(lines[-1])
    assert event["spent"] == "0.31" and event["over_by"] == "0.01"
    cli("alert", "999.99")
    cli("add", "Checking", "-999.99", "--payee", "Sofa", "--date", "2026-03-03")
    lines = (Path(cli.path).parent / "alerts.jsonl").read_text("utf-8").splitlines()
    event = json.loads(lines[-1])
    assert event["type"] == "transaction.large"
    assert (event["amount"], event["threshold"]) == ("-999.99", "999.99")
