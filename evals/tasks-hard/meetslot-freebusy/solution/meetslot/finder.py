"""Finding times when everyone can meet."""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta

from meetslot.intervals import IntervalSet
from meetslot.people import Person


def free_time(person: Person, start: datetime, end: datetime, buffer: timedelta) -> IntervalSet:
    """The part of [start, end) in which `person` is free.

    A person is free during their working hours, except during their busy time *and* for
    `buffer` before and after each busy interval, so nobody is booked straight into or out
    of another meeting. `person` is not changed.
    """
    # Shifts that start the day before can run into the window, as can shifts on local dates
    # after the UTC date of `end` for people east of UTC.
    free = person.working_time(start.date() - timedelta(days=1), end.date() + timedelta(days=1))
    free = free.copy()  # working_time() returns a cached set; never change it
    for busy_start, busy_end in person.busy:
        free.remove(busy_start - buffer, busy_end + buffer)
    return free.clip(start, end)


def _starts(free: IntervalSet, duration: timedelta, step: timedelta) -> Iterator[datetime]:
    for start, end in free:
        midnight = datetime.combine(start.date(), time())
        candidate = midnight - (midnight - start) // step * step  # round up to the grid
        while candidate + duration <= end:
            yield candidate
            candidate += step


def find_slots(
    people: Sequence[Person],
    first_day: date,
    last_day: date,
    duration: timedelta,
    *,
    buffer: timedelta = timedelta(0),
    step: timedelta = timedelta(minutes=15),
    limit: int | None = None,
) -> list[datetime]:
    """UTC start times of every slot of `duration` in which all of `people` are free.

    - The search covers the UTC dates `first_day` to `last_day`, both included: from
      00:00 UTC on `first_day` up to 00:00 UTC the day after `last_day`. A slot must lie
      entirely inside that window.
    - Each person must be free (see `free_time`) for the whole slot.
    - Slots start on multiples of `step` (which must divide a day evenly) counted from
      00:00 UTC: with the default 15 minutes, at :00, :15, :30 and :45. Every such start
      that fits is returned, so slots may overlap each other.
    - The result is sorted, and cut to the first `limit` slots when `limit` is given.

    find_slots does not change the people it is given, so an earlier call never changes the
    answer of a later one.
    """
    if duration <= timedelta(0) or step <= timedelta(0):
        raise ValueError("duration and step must be positive")
    if not people:
        raise ValueError("nobody to meet")
    window_start = datetime.combine(first_day, time())
    window_end = datetime.combine(last_day + timedelta(days=1), time())
    common = free_time(people[0], window_start, window_end, buffer)
    for person in people[1:]:
        common = common.intersection(free_time(person, window_start, window_end, buffer))
    slots = list(_starts(common, duration, step))
    return slots if limit is None else slots[:limit]


def first_slot(
    people: Sequence[Person], after: date, duration: timedelta, *, days: int = 14, **options
) -> datetime | None:
    """The earliest slot in the `days` days from `after`, or None."""
    slots = find_slots(
        people, after, after + timedelta(days=days - 1), duration, limit=1, **options
    )
    return slots[0] if slots else None
