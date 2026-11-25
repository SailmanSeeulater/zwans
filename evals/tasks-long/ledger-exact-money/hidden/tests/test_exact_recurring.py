"""Recurring entries and their instalments."""

from datetime import date

import pytest
from conftest import exact

from billfold import Book


def test_instalments_give_leftover_cents_to_the_first_ones(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    entry = book.recurring.add("Checking", "Insurer", "1000.00", "monthly", "2026-01-15",
                               instalments=12)
    exact(entry.amount, "1000.00")
    booked = book.recurring.run(until=date(2026, 12, 31))
    assert [str(t.amount) for t in booked] == ["83.34"] * 4 + ["83.33"] * 8
    exact(book.balance("Checking"), "1000.00")


def test_negative_instalments(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Dentist", "-100.00", "monthly", "2026-01-10", instalments=3)
    booked = book.recurring.run(until=date(2026, 6, 1))
    assert [str(t.amount) for t in booked] == ["-33.34", "-33.33", "-33.33"]


def test_instalments_in_yen(book: Book) -> None:
    book.add_account("Yen", currency="JPY", opened="2026-01-01")
    book.recurring.add("Yen", "Phone", "-100000", "monthly", "2026-01-10", instalments=7)
    booked = book.recurring.run(until=date(2026, 12, 1))
    assert [str(t.amount) for t in booked] == ["-14286"] * 5 + ["-14285"] * 2
    exact(book.balance("Yen"), "-100000")


def test_instalments_booked_over_several_runs(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Shop", "-0.05", "weekly", "2026-03-02", instalments=3)
    first = book.recurring.run(until=date(2026, 3, 2))
    rest = book.recurring.run(until=date(2026, 4, 1))
    assert [str(t.amount) for t in first + rest] == ["-0.02", "-0.02", "-0.01"]


def test_plain_recurring_amounts_are_exact(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Gym", "-24.90", "monthly", "2026-01-01")
    booked = book.recurring.run(until=date(2026, 3, 31))
    assert [str(t.amount) for t in booked] == ["-24.90"] * 3
    exact(book.balance("Checking"), "-74.70")


def test_recurring_refuses_floats(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    with pytest.raises(TypeError):
        book.recurring.add("Checking", "Gym", -24.9, "monthly", "2026-01-01")
