import pytest

from billfold import Book, ValidationError


def test_spending_covers_subcategories_and_refunds(household: Book) -> None:
    household.budgets.set("Food", "2026-03", "100.00")
    household.add_transaction("Checking", "2026-03-12", "2.50", payee="REWE",
                              category="Food:Groceries", memo="refund")
    (line,) = household.budgets.status("2026-03")
    assert line.spent == 42.5 + 12.25 - 2.5
    assert line.remaining == 100 - 52.25
    assert not line.over


def test_other_currencies_and_transfers_do_not_count(household: Book) -> None:
    household.budgets.set("Food", "2026-03", "100.00")
    household.transfer("Checking", "Savings", "50.00", "2026-03-10")
    assert household.budgets.line("Food", "2026-03").spent == 54.75


def test_rollover_carries_what_is_left(household: Book) -> None:
    household.budgets.set("Food", "2026-02", "80.00", rollover=True)
    household.add_transaction("Checking", "2026-02-10", "-30.00", category="Food")
    household.budgets.set("Food", "2026-03", "100.00")
    line = household.budgets.line("Food", "2026-03")
    assert line.carried == 50
    assert line.available == 150


def test_allocate_by_weight(book: Book) -> None:
    shares = book.budgets.allocate("1000.00", {"Rent": 6, "Food": 3, "Fun": 1}, "2026-04")
    assert shares == {"Rent": 600, "Food": 300, "Fun": 100}
    assert book.budgets.get("Food", "2026-04").amount == 300


def test_allocate_needs_positive_weights(book: Book) -> None:
    with pytest.raises(ValidationError):
        book.budgets.allocate("100.00", {"Rent": 0}, "2026-04")


def test_going_over_budget_alerts_once(household: Book) -> None:
    events = []
    household.on_alert(events.append)
    household.budgets.set("Food", "2026-03", "60.00")
    household.add_transaction("Checking", "2026-03-12", "-4.00", category="Food")
    assert events == []
    household.add_transaction("Checking", "2026-03-13", "-5.00", category="Food:Groceries")
    household.add_transaction("Checking", "2026-03-14", "-1.00", category="Food")
    assert [e["type"] for e in events] == ["budget.exceeded"]
    assert events[0]["category"] == "Food" and events[0]["month"] == "2026-03"


def test_large_transaction_alert(household: Book) -> None:
    events = []
    household.on_alert(events.append)
    household.set_large_transaction_alert("500.00")
    household.add_transaction("Checking", "2026-03-12", "-499.50", payee="TV")
    household.add_transaction("Checking", "2026-03-12", "-500.00", payee="Sofa")
    assert [(e["type"], e["payee"]) for e in events] == [("transaction.large", "Sofa")]
