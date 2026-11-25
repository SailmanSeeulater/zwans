from datetime import date

import pytest

from billfold import Book, DuplicateName, NotFound, UnknownCurrency, ValidationError


def test_accounts_are_found_by_name_or_id(book: Book) -> None:
    acct = book.add_account("Checking", currency="eur", opening_balance="100.00")
    assert acct.currency == "EUR"
    assert book.account("checking") is acct
    assert book.account(acct.id) is acct
    with pytest.raises(NotFound):
        book.account("Savings")


def test_names_are_unique_ignoring_case(book: Book) -> None:
    book.add_account("Checking")
    with pytest.raises(DuplicateName):
        book.add_account("CHECKING")


def test_unknown_currency_and_kind_are_refused(book: Book) -> None:
    with pytest.raises(UnknownCurrency):
        book.add_account("Pesos", currency="XXX")
    with pytest.raises(ValidationError):
        book.add_account("Piggy", kind="piggybank")


def test_opening_balance_counts_towards_the_balance(book: Book) -> None:
    book.add_account("Cash", kind="cash", opening_balance="40.00")
    book.add_transaction("Cash", "2026-03-02", "-12.50", payee="Bakery")
    assert book.balance("Cash") == 27.5
    assert book.balance("Cash", on=date(2026, 3, 1)) == 40


def test_closing_needs_an_empty_account(book: Book) -> None:
    book.add_account("Old", opening_balance="10.00")
    book.add_account("New")
    with pytest.raises(ValidationError):
        book.close_account("Old")
    book.transfer("Old", "New", "10.00", "2026-03-02")
    book.close_account("Old")
    assert [a.name for a in book.list_accounts()] == ["New"]
    assert [a.name for a in book.list_accounts(include_closed=True)] == ["New", "Old"]
    with pytest.raises(ValidationError):
        book.add_transaction("Old", "2026-03-03", "-1.00")


def test_rename_keeps_transactions(book: Book) -> None:
    book.add_account("Checking", opening_balance="5.00")
    book.add_transaction("Checking", "2026-03-02", "-2.50")
    book.rename_account("Checking", "Main")
    assert book.balance("Main") == 2.5
