"""Series: the same appointment repeated by a Recurrence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from .booking import BookingService
from .errors import BookingError
from .ids import next_id
from .models import Appointment, Series
from .recurrence import Recurrence
from .repository import Repository
from .storage import Store
from .timeutil import instant


@dataclass
class SeriesResult:
    series: Series | None
    booked: list[Appointment] = field(default_factory=list)
    skipped: list[tuple[datetime, str]] = field(default_factory=list)


class SeriesService:
    def __init__(
        self,
        store: Store,
        repo: Repository,
        booking: BookingService,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.repo = repo
        self.booking = booking
        self.clock = clock

    def book_series(
        self,
        *,
        clinic: str,
        clinician: str,
        room: str,
        patient: str,
        start: datetime | str,
        minutes: int,
        rule: Recurrence,
        kind: str = "consult",
    ) -> SeriesResult:
        """Book every occurrence that can be booked; the others are reported as skipped.

        Nothing is kept if no occurrence at all can be booked.
        """
        place = self.repo.clinic(clinic)
        first = self.booking.when(place, start)
        series_id = next_id(self.store.counters, "series")
        result = SeriesResult(series=None)
        for when in rule.occurrences(instant(first)):
            try:
                appt = self.booking.book(
                    clinic=clinic,
                    clinician=clinician,
                    room=room,
                    patient=patient,
                    start=when,
                    minutes=minutes,
                    kind=kind,
                    series=series_id,
                    source="series",
                )
            except BookingError as exc:
                result.skipped.append((when, str(exc)))
            else:
                result.booked.append(appt)
        if not result.booked:
            reasons = "; ".join(sorted({why for _, why in result.skipped}))
            raise BookingError(f"no appointment of the series could be booked: {reasons}")
        series = Series(
            id=series_id,
            clinic=clinic,
            clinician=clinician,
            room=room,
            patient=patient,
            start=first,
            minutes=minutes,
            rule=rule.to_dict(),
            kind=kind,
        )
        self.store.series[series.id] = series
        result.series = series
        return result

    def cancel_series(self, series_id: str, *, from_day: date | None = None) -> list[Appointment]:
        """Cancel the series' appointments still to come (from `from_day` on, if given)."""
        self.repo.series(series_id)
        now = self.clock()
        cancelled = []
        for appt in self.repo.appointments(series=series_id, status="booked"):
            if instant(appt.start) < instant(now):
                continue
            if from_day is not None and appt.start.date() < from_day:
                continue
            cancelled.append(self.booking.cancel(appt.id, reason="series cancelled"))
        return cancelled
