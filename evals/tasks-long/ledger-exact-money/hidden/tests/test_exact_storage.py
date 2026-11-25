"""Rule 5: the data file holds strings, version 3, and old files come back exact."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import exact

from billfold import Book, FixedClock


def floats_in(value, path="$") -> list[str]:
    """Every JSON float in a document, by path."""
    if isinstance(value, float):
        return [f"{path} = {value!r}"]
    if isinstance(value, dict):
        return [hit for key, item in value.items() for hit in floats_in(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [hit for i, item in enumerate(value) for hit in floats_in(item, f"{path}[{i}]")]
    return []


def strings_in(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings_in(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(strings_in(v) for v in value)) if value else set()
    return set()


def reopen(path: Path) -> Book:
    return Book.open(path, clock=FixedClock("2026-03-01"))


def full_book(book: Book) -> Book:
    book.add_account("Checking", opening_balance="0.70", opened="2026-01-01")
    book.add_account("Yen", currency="JPY", opening_balance="15000", opened="2026-01-01")
    a = book.add_transaction("Checking", "2026-03-02", "-0.10", payee="Kiosk")
    book.add_transaction("Checking", "2026-03-02", "-0.20", payee="Kiosk")
    txn = book.add_transaction("Checking", "2026-03-03", "-33.33", payee="Market")
    book.split_transaction(txn.id, {"Food": "-20.00", "Household": "-13.33"})
    book.add_transaction("Yen", "2026-03-04", "-1200", payee="Ramen Ya")
    book.edit_transaction(a.id, amount="-0.15")
    book.budgets.set("Food", "2026-03", "120.10", rollover=True)
    book.recurring.add("Checking", "Gym", "-24.90", "monthly", "2026-04-01")
    book.set_rate("EUR", "USD", "1.0825", "2026-01-01")
    book.add_rule("Thirds", ["payee~flat"], split={"A": "33.3", "B": "33.3", "C": "33.4"})
    book.set_large_transaction_alert("999.99")
    book.balance("Checking")
    book.balance("Yen")
    return book


def test_saved_files_hold_no_floats(book: Book, tmp_path: Path) -> None:
    path = full_book(book).save(tmp_path / "book.json")
    doc = json.loads(path.read_text("utf-8"))
    assert doc["version"] == 3
    assert floats_in(doc) == []
    strings = strings_in(doc)
    for text in ("0.70", "15000", "-0.15", "-0.20", "-33.33", "-20.00", "-13.33", "-1200",
                 "120.10", "-24.90", "1.0825", "999.99", "33.3", "33.4"):
        assert text in strings, f"{text} should be in the file as a string"


def test_cached_balances_come_back_exact(book: Book, tmp_path: Path) -> None:
    path = full_book(book).save(tmp_path / "book.json")
    again = reopen(path)
    exact(again.balance("Checking"), "-32.98")
    exact(again.balance("Yen"), "13800")
    again.add_transaction("Checking", "2026-03-05", "-0.01")
    exact(again.balance("Checking"), "-32.99")


def test_everything_comes_back_exact(book: Book, tmp_path: Path) -> None:
    path = full_book(book).save(tmp_path / "book.json")
    again = reopen(path)
    exact(again.account("Checking").opening_balance, "0.70")
    txns = again.transactions_for("Checking")
    assert [str(t.amount) for t in txns] == ["-0.15", "-0.20", "-33.33"]
    assert [str(s.amount) for s in txns[2].splits] == ["-20.00", "-13.33"]
    exact(again.budgets.get("Food", "2026-03").amount, "120.10")
    exact(again.recurring.all()[0].amount, "-24.90")
    exact(again.convert("10.00", "EUR", "USD", date(2026, 3, 1)), "10.83")
    events = []
    again.on_alert(events.append)
    again.add_transaction("Checking", "2026-03-05", "-999.98", payee="TV")
    flat = again.add_transaction("Checking", "2026-03-05", "-999.99", payee="Flat")
    assert [e["payee"] for e in events] == ["Flat"]
    assert [str(s.amount) for s in flat.splits] == ["-333.00", "-333.00", "-333.99"]


def test_undo_after_reopening_is_exact(book: Book, tmp_path: Path) -> None:
    path = full_book(book).save(tmp_path / "book.json")
    again = reopen(path)
    again.undo()
    first = again.transactions_for("Checking")[0]
    exact(first.amount, "-0.10")
    exact(again.balance("Checking"), "-32.93")


def test_undo_in_memory_is_exact(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-0.10")
    book.edit_transaction(txn.id, amount="-0.20")
    book.undo()
    exact(book.transaction(txn.id).amount, "-0.10")
    exact(book.balance("Checking"), "-0.10")
    book.delete_transaction(txn.id)
    book.undo()
    exact(book.transaction(txn.id).amount, "-0.10")


def test_old_float_files_open_exact(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    exact(book.balance("Checking"), "1281.04")
    exact(book.balance("Yen"), "13800")
    exact(book.balance("Card"), "-0.30")
    exact(book.account("Checking").opening_balance, "100.10")
    amounts = [str(t.amount) for t in book.transactions_for("Checking")]
    assert amounts == ["-0.10", "-0.20", "-19.99", "-33.33", "1234.56"]
    split = book.transactions_for("Checking")[3]
    assert [str(s.amount) for s in split.splits] == ["-20.00", "-13.33"]


def test_old_cached_balances_are_rounded(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    exact(book.balance("Card"), "-0.30")
    book.add_transaction("Card", "2026-01-20", "-0.10")
    exact(book.balance("Card"), "-0.40")


def test_old_budgets_rules_and_rates_are_exact(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    food = book.budgets.line("Food", "2026-01")
    exact(food.budgeted, "120.10")
    exact(food.spent, "20.30")
    exact(food.remaining, "99.80")
    exact(book.budgets.line("Subscriptions", "2026-01").remaining, "0.00")
    exact(book.convert("10.10", "EUR", "GBP", date(2026, 2, 1)), "8.59")
    exact(book.convert("10.00", "EUR", "USD", date(2026, 2, 1)), "10.83")
    exact(book.convert("10.01", "EUR", "JPY", date(2026, 2, 1)), "1617")
    streaming = book.add_transaction("Checking", "2026-02-01", "-19.99", payee="Streamly Plus")
    assert streaming.category == "Subscriptions"
    costco = book.add_transaction("Checking", "2026-02-01", "-9.99", payee="COSTCO")
    assert [str(s.amount) for s in costco.splits] == ["-5.00", "-4.99"]


def test_old_recurring_entries_are_exact(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    booked = book.recurring.run(until=date(2026, 3, 31))
    by_payee = {}
    for txn in booked:
        by_payee.setdefault(txn.payee, []).append(str(txn.amount))
    assert by_payee == {"Insurer": ["-33.34", "-33.33", "-33.33"], "Gym": ["-24.90", "-24.90"]}


def test_old_threshold_still_alerts(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    events = []
    book.on_alert(events.append)
    book.add_transaction("Checking", "2026-02-01", "-999.98", payee="TV")
    book.add_transaction("Checking", "2026-02-01", "-999.99", payee="Sofa")
    assert [(e["type"], e["payee"]) for e in events] == [("transaction.large", "Sofa")]
    assert events[0]["threshold"] == "999.99"


def test_old_history_undoes_exactly(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    book.undo()
    exact(book.transaction("txn-2").amount, "-0.30")
    exact(book.balance("Checking"), "1280.94")


def test_old_files_are_saved_as_version_3(legacy_floats: Path) -> None:
    book = reopen(legacy_floats)
    book.balance("Card")
    book.save()
    doc = json.loads(legacy_floats.read_text("utf-8"))
    assert doc["version"] == 3
    assert floats_in(doc) == []
    strings = strings_in(doc)
    for text in ("1.0825", "0.85", "161.5", "999.99", "19.99", "120.10", "-0.30", "-24.90"):
        assert text in strings, f"{text} should be in the file as a string"
    again = reopen(legacy_floats)
    exact(again.balance("Card"), "-0.30")
    exact(again.balance("Checking"), "1281.04")
    again.undo()
    exact(again.transaction("txn-2").amount, "-0.30")


def test_version_1_float_files_open_exact(legacy_v1_floats: Path) -> None:
    book = reopen(legacy_v1_floats)
    exact(book.balance("Current"), "10.41")
    assert [str(t.amount) for t in book.transactions_for("Current")] == ["-0.10", "-0.20", "10.01"]
    exact(book.budgets.get("Travel", "2025-06").amount, "12.30")
    exact(book.convert("0.50", "GBP", "EUR", date(2025, 7, 1)), "0.59")
    book.save()
    assert floats_in(json.loads(legacy_v1_floats.read_text("utf-8"))) == []
