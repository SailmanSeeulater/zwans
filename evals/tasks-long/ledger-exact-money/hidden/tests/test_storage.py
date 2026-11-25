import json
from datetime import date
from pathlib import Path

import pytest

from billfold import Book, FixedClock, StorageError


def test_round_trip(household: Book, tmp_path: Path) -> None:
    household.add_rule("Coffee", ["payee~cafe", "amount<5"], category="Food:Coffee")
    household.budgets.set("Food", "2026-03", "100.00", rollover=True)
    household.recurring.add("Checking", "Phone", "-20.00", "monthly", "2026-04-05")
    household.set_rate("EUR", "USD", "1.25", "2026-03-01")
    household.set_large_transaction_alert("500.00")
    path = household.save(tmp_path / "book.json")

    again = Book.open(path, clock=FixedClock("2026-03-01"))
    assert again.balance("Checking") == household.balance("Checking")
    assert [t.payee for t in again.transactions_for()] == [
        t.payee for t in household.transactions_for()]
    assert again.budgets.line("Food", "2026-03").remaining == 45.25
    assert again.recurring.all()[0].amount == -20
    assert again.convert("8.00", "EUR", "USD", date(2026, 3, 2)) == 10
    assert again.settings.large_transaction == 500
    assert again.add_transaction("Checking", "2026-03-20", "-4.50", payee="Cafe").category == "Food:Coffee"
    assert again.add_account("Wallet").id == "acc-4"


def test_undo_survives_saving(household: Book, tmp_path: Path) -> None:
    txn = household.add_transaction("Checking", "2026-03-10", "-5.00", payee="Kiosk")
    household.edit_transaction(txn.id, amount="-7.50")
    path = household.save(tmp_path / "book.json")
    again = Book.open(path, clock=FixedClock("2026-03-01"))
    again.undo()
    assert again.transaction(txn.id).amount == -5


def test_a_missing_file_is_an_empty_book(tmp_path: Path) -> None:
    book = Book.open(tmp_path / "new.json")
    assert book.accounts == {}


def test_previous_copy_is_kept(household: Book, tmp_path: Path) -> None:
    path = household.save(tmp_path / "book.json")
    household.add_transaction("Checking", "2026-03-10", "-5.00")
    household.save()
    assert (tmp_path / "book.json.bak").exists()


def test_newer_files_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "book.json"
    path.write_text(json.dumps({"version": 99}), "utf-8")
    with pytest.raises(StorageError):
        Book.open(path)


def test_version_1_files_open(legacy_v1: Path) -> None:
    book = Book.open(legacy_v1, clock=FixedClock("2026-03-01"))
    assert [a.name for a in book.list_accounts()] == ["Girokonto", "Tagesgeld"]
    assert book.balance("Girokonto") == 1795.5
    assert book.budgets.get("Lebensmittel", "2025-11").amount == 300
    assert book.convert("10.00", "EUR", "USD", date(2025, 12, 1)) == 10.5


def test_version_2_files_open(legacy_v2: Path) -> None:
    book = Book.open(legacy_v2, clock=FixedClock("2026-03-01"))
    assert book.balance("Checking") == 3446.75
    assert book.balance("Savings") == 10250
    txn = book.add_transaction("Checking", "2026-02-20", "-15.99", payee="NETFLIX")
    assert txn.category == "Subscriptions"
    book.undo()
    book.undo()
    assert book.balance("Checking") == 3446.75 + 64.5


def test_saving_an_old_file_upgrades_it(legacy_v1: Path) -> None:
    book = Book.open(legacy_v1, clock=FixedClock("2026-03-01"))
    book.save()
    doc = json.loads(legacy_v1.read_text("utf-8"))
    assert doc["version"] > 1
    assert Book.open(legacy_v1).balance("Girokonto") == 1795.5
