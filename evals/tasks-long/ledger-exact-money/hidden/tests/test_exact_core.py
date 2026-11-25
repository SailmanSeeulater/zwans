"""Rules 1-4 of "Exact money": the type, input, exact arithmetic, conversions, even splits."""

from datetime import date
from decimal import Decimal

import pytest
from conftest import exact

from billfold import Book, MoneyError, parse_amount


def test_parse_amount_returns_decimals_exactly_as_written() -> None:
    assert parse_amount("1,234.50") == Decimal("1234.50")
    assert isinstance(parse_amount("1,234.50"), Decimal)
    assert parse_amount("(12.00)") == Decimal("-12.00")
    assert parse_amount("12.00-") == Decimal("-12.00")
    assert parse_amount("€0.10") == Decimal("0.10")
    assert parse_amount(7) == Decimal(7)


def test_floats_are_refused() -> None:
    with pytest.raises(TypeError):
        parse_amount(0.1)


def test_floats_are_refused_by_the_book(book: Book) -> None:
    book.add_account("Checking")
    with pytest.raises(TypeError):
        book.add_transaction("Checking", "2026-03-02", 0.1)
    with pytest.raises(TypeError):
        book.add_account("Cash", opening_balance=12.5)
    with pytest.raises(TypeError):
        book.set_rate("EUR", "USD", 1.08, "2026-03-01")
    assert book.transactions_for("Checking") == []


def test_too_many_places_are_refused_not_rounded(book: Book) -> None:
    book.add_account("Checking")
    book.add_account("Yen", currency="JPY")
    with pytest.raises(MoneyError):
        book.add_transaction("Checking", "2026-03-02", "12.345")
    with pytest.raises(MoneyError):
        book.add_transaction("Yen", "2026-03-02", "1.5")
    exact(book.add_transaction("Yen", "2026-03-02", "1,500").amount, "1500")
    assert len(book.transactions_for()) == 1


def test_amounts_and_balances_are_exact(pennies: Book) -> None:
    exact(pennies.balance("Checking"), "1214.97")
    exact(pennies.balance("Checking", on=date(2026, 3, 2)), "0.40")
    exact(pennies.balance("Yen"), "13800")
    txn = pennies.add_transaction("Checking", "2026-03-06", "0.1")
    exact(txn.amount, "0.10")
    exact(pennies.account("Checking").opening_balance, "0.70")


def test_balances_stay_exact_through_many_small_changes(book: Book) -> None:
    book.add_account("Coffee")
    for _ in range(30):
        book.add_transaction("Coffee", "2026-03-02", "-0.10", payee="Cafe")
    exact(book.balance("Coffee"), "-3.00")
    first = book.transactions_for("Coffee")[0]
    book.edit_transaction(first.id, amount="-0.20")
    exact(book.balance("Coffee"), "-3.10")
    book.delete_transaction(first.id)
    exact(book.balance("Coffee"), "-2.90")


def test_even_split_gives_leftover_cents_to_the_first_parts(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "100.00")
    split = book.split_transaction(txn.id, ["A", "B", "C"])
    assert [str(s.amount) for s in split.splits] == ["33.34", "33.33", "33.33"]
    out = book.add_transaction("Checking", "2026-03-02", "-0.05")
    split = book.split_transaction(out.id, ["A", "B", "C"])
    assert [str(s.amount) for s in split.splits] == ["-0.02", "-0.02", "-0.01"]
    exact(book.balance("Checking"), "99.95")


def test_split_by_amounts_is_checked_exactly(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-0.30")
    split = book.split_transaction(txn.id, {"Food": "-0.10", "Fun": "-0.20"})
    assert [s.amount for s in split.splits] == [Decimal("-0.10"), Decimal("-0.20")]
    assert all(isinstance(s.amount, Decimal) for s in split.splits)


def test_conversion_rounds_once_half_away_from_zero(book: Book) -> None:
    book.set_rate("EUR", "USD", "0.25", "2026-01-01")
    exact(book.convert("10.50", "EUR", "USD", date(2026, 3, 1)), "2.63")
    exact(book.convert("-10.50", "EUR", "USD", date(2026, 3, 1)), "-2.63")
    exact(book.convert("10.70", "EUR", "USD", date(2026, 3, 1)), "2.68")


def test_conversion_through_the_opposite_rate_divides(book: Book) -> None:
    book.set_rate("USD", "EUR", "0.8", "2026-01-01")
    exact(book.convert("0.10", "EUR", "USD", date(2026, 3, 1)), "0.13")
    exact(book.convert("2.50", "EUR", "USD", date(2026, 3, 1)), "3.13")


def test_rates_are_exact_decimals(book: Book) -> None:
    book.set_rate("EUR", "GBP", "0.85", "2026-01-01")
    exact(book.convert("10.10", "EUR", "GBP", date(2026, 3, 1)), "8.59")


def test_conversion_into_yen(book: Book) -> None:
    book.set_rate("EUR", "JPY", "161.5", "2026-01-01")
    exact(book.convert("10.01", "EUR", "JPY", date(2026, 3, 1)), "1617")


def test_cross_currency_transfer(book: Book) -> None:
    book.add_account("Checking", opening_balance="100.00")
    book.add_account("Dollars", currency="USD")
    book.set_rate("EUR", "USD", "0.25", "2026-01-01")
    out_leg, in_leg = book.transfer("Checking", "Dollars", "10.50", "2026-03-02")
    exact(out_leg.amount, "-10.50")
    exact(in_leg.amount, "2.63")
    _, given = book.transfer("Checking", "Dollars", "0.10", "2026-03-02", rate="1.25")
    exact(given.amount, "0.13")
    exact(book.balance("Dollars"), "2.76")


def test_closing_an_account_needs_exactly_zero(book: Book) -> None:
    book.add_account("Old", opening_balance="0.30")
    book.add_transaction("Old", "2026-03-02", "-0.10")
    book.add_transaction("Old", "2026-03-02", "-0.20")
    book.close_account("Old")
    assert book.account("Old").closed
