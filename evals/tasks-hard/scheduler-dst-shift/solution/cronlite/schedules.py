"""Schedules: when a job runs. Every schedule answers one question: given an instant,
when is the next run strictly after it?"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from cronlite.timeutil import parse_duration, parse_hhmm
from cronlite.zones import Zone

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS = frozenset(range(5))
EVERY_DAY = frozenset(range(7))


class ScheduleError(ValueError):
    pass


class Schedule(ABC):
    @abstractmethod
    def next_after(self, after: datetime, zone: Zone) -> datetime:
        """The first run strictly after the instant `after`, as an aware UTC datetime."""

    @abstractmethod
    def describe(self) -> str: ...


@dataclass(frozen=True)
class AtTime(Schedule):
    """At a wall-clock time on some days of the week."""

    at: time
    days: frozenset[int] = EVERY_DAY

    def next_after(self, after: datetime, zone: Zone) -> datetime:
        # Work in local calendar days and convert each day's run time separately: a day
        # is not always 24 hours long, and a run moved out of a DST gap must not drag
        # the following days' runs with it.
        day = zone.to_local(after).date()
        while True:
            if day.weekday() in self.days:
                candidate = zone.to_utc(datetime.combine(day, self.at))
                if candidate > after:
                    return candidate
            day += timedelta(days=1)

    def describe(self) -> str:
        if self.days == EVERY_DAY:
            which = "daily"
        elif self.days == WEEKDAYS:
            which = "weekdays"
        else:
            which = ",".join(DAY_NAMES[d] for d in sorted(self.days))
        return f"{which} {self.at.strftime('%H:%M')}"


@dataclass(frozen=True)
class Every(Schedule):
    """Every `interval` of elapsed time, counted from midnight UTC on 1 Jan 2000."""

    interval: timedelta

    ANCHOR = datetime(2000, 1, 1, tzinfo=UTC)

    def next_after(self, after: datetime, zone: Zone) -> datetime:
        elapsed = after.astimezone(UTC) - self.ANCHOR
        steps = elapsed // self.interval + 1
        return self.ANCHOR + steps * self.interval

    def describe(self) -> str:
        minutes = int(self.interval.total_seconds()) // 60
        return f"every {minutes // 60}h" if minutes % 60 == 0 else f"every {minutes}m"


def parse_schedule(text: str) -> Schedule:
    """'daily 02:30', 'weekdays 08:00', 'mon,thu 07:15', 'every 30m', 'every 2h'."""
    words = text.strip().lower().split()
    if len(words) != 2:
        raise ScheduleError(f"a schedule is two words, like 'daily 02:30': {text!r}")
    which, value = words
    try:
        if which == "every":
            return Every(parse_duration(value))
        at = parse_hhmm(value)
    except ValueError as exc:
        raise ScheduleError(str(exc)) from None
    if which == "daily":
        return AtTime(at, EVERY_DAY)
    if which == "weekdays":
        return AtTime(at, WEEKDAYS)
    days = set()
    for name in which.split(","):
        if name not in DAY_NAMES:
            raise ScheduleError(f"unknown day {name!r} in {text!r}")
        days.add(DAY_NAMES.index(name))
    return AtTime(at, frozenset(days))


def runs_between(schedule: Schedule, zone: Zone, start: datetime, end: datetime) -> list[datetime]:
    """Every run in (start, end], in order."""
    runs = []
    moment = schedule.next_after(start, zone)
    while moment <= end:
        runs.append(moment)
        moment = schedule.next_after(moment, zone)
        if len(runs) > 100_000:
            raise RuntimeError("too many runs; is the interval tiny?")
    return runs
