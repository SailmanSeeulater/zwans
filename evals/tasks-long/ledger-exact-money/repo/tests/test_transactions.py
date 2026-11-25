from datetime import date

import pytest

from billfold import Book, NothingToUndo, ValidationError


def test_add_edit_delete(household: Book) -> None:
    txn = household.add_transaction("Checking", "2026-03-10", "-7.50", payee="Kiosk")
    assert household.balance("Checking") == 1000 - 42.5 + 2500 - 12.25 - 1100 - 7.5
    household.edit_transaction(txn.id, amount="-8.00", payee="Kiosk am Eck")
    assert household.transaction(txn.id).payee == "Kiosk am Eck"
    assert household.balance("Checking") == 1000 - 42.5 + 2500 - 12.25 - 1100 - 8
    household.delete_transaction(txn.id)
    assert household.balance("Checking") == 1000 - 42.5 + 2500 - 12.25 - 1100


def test_amounts_are_read_like_people_write_them(book: Book) -> None:
    book.add_account("Checking")
    book.add_transaction("Checking", "2026-03-02", "1,234.50", payee="Bonus")
    book.add_transaction("Checking", "2026-03-02", "(34.50)", payee="Shoes")
    book.add_transaction("Checking", "2026-03-02", "€ 10.00-", payee="Fee")
    assert book.balance("Checking") == 1190


def test_balance_on_a_day(household: Book) -> None:
    assert household.balance("Checking", on=date(2026, 3, 2)) == 957.5
    assert household.balance("Checking", on=date(2026, 3, 4)) == 3457.5


def test_even_split(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-60.00", payee="Market")
    split = book.split_transaction(txn.id, ["Food", "Household", "Garden"])
    assert [s.amount for s in split.splits] == [-20, -20, -20]
    assert [s.category for s in split.splits] == ["Food", "Household", "Garden"]
    assert book.balance("Checking") == -60


def test_split_by_amounts_must_add_up(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-60.00")
    with pytest.raises(ValidationError):
        book.split_transaction(txn.id, {"Food": "-50.00", "Garden": "-5.00"})
    split = book.split_transaction(txn.id, {"Food": "-50.00", "Garden": "-10.00"})
    assert [s.amount for s in split.splits] == [-50, -10]


def test_transfer_moves_money_both_ways(household: Book) -> None:
    out_leg, in_leg = household.transfer("Checking", "Savings", "250.00", "2026-03-10")
    assert out_leg.amount == -250 and in_leg.amount == 250
    assert out_leg.transfer_id == in_leg.transfer_id
    household.delete_transaction(in_leg.id)
    assert household.balance("Savings") == 5000
    assert household.balance("Checking") == 1000 - 42.5 + 2500 - 12.25 - 1100


def test_transfer_between_currencies_uses_the_rate(household: Book) -> None:
    household.set_rate("EUR", "USD", "1.25", "2026-03-01")
    _, in_leg = household.transfer("Checking", "Dollars", "100.00", "2026-03-10")
    assert in_leg.amount == 125
    _, back = household.transfer("Dollars", "Checking", "50.00", "2026-03-11")
    assert back.amount == 40


def test_undo_takes_back_one_change_at_a_time(household: Book) -> None:
    before = household.balance("Checking")
    txn = household.add_transaction("Checking", "2026-03-10", "-5.00")
    household.edit_transaction(txn.id, amount="-6.00")
    household.undo()
    assert household.transaction(txn.id).amount == -5
    household.undo()
    assert household.balance("Checking") == before
    for _ in range(len(household.history)):
        household.undo()
    with pytest.raises(NothingToUndo):
        household.undo()


def test_cannot_change_a_transfer_amount(household: Book) -> None:
    out_leg, _ = household.transfer("Checking", "Savings", "10.00", "2026-03-10")
    with pytest.raises(ValidationError):
        household.edit_transaction(out_leg.id, amount="-20.00")
