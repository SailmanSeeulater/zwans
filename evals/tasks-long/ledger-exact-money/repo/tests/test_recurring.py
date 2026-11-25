from datetime import date

from billfold import Book


def test_monthly_entries_are_booked_up_to_a_day(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Landlord", "-1100.00", "monthly", "2026-01-01",
                       category="Rent")
    booked = book.recurring.run(until=date(2026, 3, 15))
    assert [t.date for t in booked] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert all(t.category == "Rent" and t.amount == -1100 for t in booked)
    assert book.recurring.run(until=date(2026, 3, 15)) == []


def test_month_end_entries_stay_at_month_end(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Gym", "-30.00", "monthly", "2026-01-31")
    booked = book.recurring.run(until=date(2026, 4, 30))
    assert [t.date.isoformat() for t in booked] == [
        "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


def test_weekly_with_an_end(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.recurring.add("Checking", "Cleaner", "-40.00", "weekly", "2026-03-02",
                       end="2026-03-20")
    booked = book.recurring.run(until=date(2026, 4, 30))
    assert [t.date.day for t in booked] == [2, 9, 16]


def test_instalments_add_up_to_the_total(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    entry = book.recurring.add("Checking", "Insurer", "-1200.00", "monthly", "2026-01-15",
                               instalments=12)
    booked = book.recurring.run(until=date(2027, 6, 1))
    assert len(booked) == 12
    assert all(t.amount == -100 for t in booked)
    assert book.recurring.get(entry.id).finished


def test_undoing_a_run_puts_the_entry_back(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    entry = book.recurring.add("Checking", "Phone", "-20.00", "monthly", "2026-01-05")
    book.recurring.run(until=date(2026, 2, 10))
    book.undo()
    assert book.transactions_for("Checking") == []
    assert book.recurring.get(entry.id).next_date == date(2026, 1, 5)
    assert len(book.recurring.run(until=date(2026, 2, 10))) == 2


def test_paused_entries_wait(book: Book) -> None:
    book.add_account("Checking", opened="2026-01-01")
    entry = book.recurring.add("Checking", "Paper", "-8.00", "monthly", "2026-01-01")
    book.recurring.pause(entry.id)
    assert book.recurring.run(until=date(2026, 3, 1)) == []
    book.recurring.resume(entry.id)
    assert len(book.recurring.run(until=date(2026, 3, 1))) == 3
