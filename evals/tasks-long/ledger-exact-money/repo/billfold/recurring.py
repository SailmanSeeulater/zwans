"""Recurring entries: rent, salary, subscriptions, and things paid off in instalments.

An entry has a frequency and the date it is next due. `run(until)` books every
occurrence due up to that day. With `instalments=n` the entry's amount is a total paid
in n parts, after which the entry is finished.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import TYPE_CHECKING

from .currencies import get_currency
from .dates import add_months, parse_date
from .errors import NotFound, ValidationError
from .models import FREQUENCIES, RecurringEntry, Transaction
from .money import parse_amount, round_money

if TYPE_CHECKING:
    from .book import Book

_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
_DAYS = {"weekly": 7, "fortnightly": 14}


def advance(day: date, frequency: str, anchor_day: int) -> date:
    if frequency in _DAYS:
        return day + timedelta(days=_DAYS[frequency])
    if frequency in _MONTHS:
        return add_months(day, _MONTHS[frequency], anchor_day)
    raise ValidationError(f"unknown frequency {frequency!r}")


def step_back(day: date, frequency: str, anchor_day: int) -> date:
    if frequency in _DAYS:
        return day - timedelta(days=_DAYS[frequency])
    return add_months(day, -_MONTHS[frequency], anchor_day)


class Recurring:
    def __init__(self, book: Book) -> None:
        self.book = book
        self._entries: dict[str, RecurringEntry] = {}

    def add(
        self,
        account: str,
        payee: str,
        amount: object,
        frequency: str,
        start: date | str,
        *,
        category: str | None = None,
        memo: str = "",
        end: date | str | None = None,
        instalments: int | None = None,
    ) -> RecurringEntry:
        acct = self.book.account(account)
        if frequency not in FREQUENCIES:
            raise ValidationError(f"frequency must be one of {', '.join(FREQUENCIES)}")
        if instalments is not None and instalments < 1:
            raise ValidationError("instalments must be at least 1")
        first = parse_date(start)
        entry = RecurringEntry(
            id=self.book.ids.next("rec"),
            account=acct.id,
            payee=payee,
            amount=round_money(parse_amount(amount), acct.currency),
            frequency=frequency,
            start=first,
            next_date=first,
            category=self.book.categories.ensure(category),
            memo=memo,
            end=parse_date(end) if end else None,
            instalments=instalments,
        )
        self._entries[entry.id] = entry
        return entry

    def load(self, entry: RecurringEntry) -> None:
        self._entries[entry.id] = entry

    def get(self, entry_id: str) -> RecurringEntry:
        try:
            return self._entries[entry_id]
        except KeyError:
            raise NotFound(f"no recurring entry {entry_id!r}") from None

    def all(self) -> list[RecurringEntry]:
        return sorted(self._entries.values(), key=lambda e: int(e.id.rpartition("-")[2]))

    def remove(self, entry_id: str) -> RecurringEntry:
        entry = self.get(entry_id)
        del self._entries[entry_id]
        return entry

    def pause(self, entry_id: str) -> None:
        self.get(entry_id).active = False

    def resume(self, entry_id: str) -> None:
        self.get(entry_id).active = True

    def amount_for(self, entry: RecurringEntry, index: int) -> float:
        """What occurrence number `index` (from 0) of an entry is booked for."""
        if not entry.instalments:
            return entry.amount
        currency = self.book.accounts[entry.account].currency
        places = get_currency(currency).exponent
        count = entry.instalments
        share = round(entry.amount / count, places)
        if index < count - 1:
            return share
        return round(entry.amount - share * (count - 1), places)

    def due(self, until: date) -> list[tuple[RecurringEntry, date]]:
        """Every (entry, day) due on or before `until`, in date order."""
        found = []
        for entry in self.all():
            if not entry.active:
                continue
            day, done = entry.next_date, entry.done
            while day <= until:
                if entry.end is not None and day > entry.end:
                    break
                if entry.instalments is not None and done >= entry.instalments:
                    break
                found.append((entry, day))
                day = advance(day, entry.frequency, entry.start.day)
                done += 1
        found.sort(key=lambda pair: (pair[1], pair[0].id))
        return found

    def run(self, until: date | None = None) -> list[Transaction]:
        until = until or self.book.clock.today()
        booked = []
        for entry, day in self.due(until):
            txn = self.book.new_transaction(
                entry.account,
                day,
                str(self.amount_for(entry, entry.done)),
                entry.payee,
                entry.memo,
                entry.category,
                apply_rules=entry.category is None,
            )
            txn.recurring_id = entry.id
            booked.append(txn)
            entry.done += 1
            entry.next_date = advance(day, entry.frequency, entry.start.day)
        if booked:
            self.book.commit(booked, "recurring", f"booked {len(booked)} recurring entries")
        return booked

    def rewind(self, removed: Iterable[Transaction]) -> None:
        """Undo support: step entries back for occurrences that were taken out again."""
        for txn in removed:
            entry = self._entries.get(txn.recurring_id or "")
            if entry is None:
                continue
            entry.done = max(0, entry.done - 1)
            entry.next_date = min(entry.next_date, txn.date)
