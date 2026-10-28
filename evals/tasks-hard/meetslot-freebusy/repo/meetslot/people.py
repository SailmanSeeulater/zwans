"""People, their working hours and their busy time."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from meetslot.intervals import Interval, IntervalSet

MONDAY_TO_FRIDAY = frozenset(range(5))


@dataclass
class Person:
    """Someone who can be invited to a meeting.

    - `utc_offset` is the person's local time minus UTC: `timedelta(hours=2)` for someone in
      Berlin in summer, `timedelta(hours=-5)` in New York in winter. It is fixed; meetslot
      does not know about daylight-saving changes.
    - `work_start` and `work_end` are the person's working hours in *local* time. If
      `work_end` is not after `work_start` the shift runs overnight: 22:00-06:00 starts at
      22:00 local time and ends at 06:00 local time the next day.
    - `workdays` are the local weekdays (Monday is 0) on which a shift *starts*. A night
      shift that starts on Friday evening still runs into Saturday morning.
    - `busy` are the person's existing commitments, as UTC intervals.
    """

    name: str
    email: str
    utc_offset: timedelta = timedelta(0)
    work_start: time = time(9)
    work_end: time = time(17)
    workdays: frozenset[int] = MONDAY_TO_FRIDAY
    busy: list[Interval] = field(default_factory=list)
    _shift_cache: dict[tuple[date, date], IntervalSet] = field(
        default_factory=dict, repr=False, compare=False
    )

    def shift(self, day: date) -> Interval | None:
        """The UTC interval of the shift that starts on local date `day`, if there is one."""
        if day.weekday() not in self.workdays:
            return None
        start = datetime.combine(day, self.work_start) + self.utc_offset
        end = datetime.combine(day, self.work_end) + self.utc_offset
        return start, end

    def working_time(self, first_day: date, last_day: date) -> IntervalSet:
        """The UTC working time of every shift starting on a local date in [first_day, last_day].

        Planning the same range again is common, so the result is cached per range.
        """
        key = (first_day, last_day)
        if key not in self._shift_cache:
            shifts = IntervalSet()
            day = first_day
            while day <= last_day:
                interval = self.shift(day)
                if interval is not None:
                    shifts.add(*interval)
                day += timedelta(days=1)
            self._shift_cache[key] = shifts
        return self._shift_cache[key]

    def add_busy(self, start: datetime, end: datetime) -> None:
        if start >= end:
            raise ValueError(f"{self.name}: busy time must end after it starts")
        self.busy.append((start, end))
