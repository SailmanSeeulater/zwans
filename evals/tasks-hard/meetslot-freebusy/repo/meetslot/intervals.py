"""Sets of time made of half-open intervals.

All datetimes in meetslot are naive and in UTC.
"""

from bisect import bisect_right
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

Interval = tuple[datetime, datetime]


class IntervalSet:
    """A set of instants, stored as half-open intervals [start, end).

    The set is kept normalised: its intervals are sorted, and intervals that overlap *or
    touch* are merged, so iterating always yields disjoint intervals with a gap between
    each one and the next. [9:00, 10:00) and [10:00, 11:00) are stored as [9:00, 11:00).
    Empty intervals (start >= end) are ignored by add() and remove().
    """

    def __init__(self, intervals: Iterable[Interval] = ()):
        self._starts: list[datetime] = []
        self._ends: list[datetime] = []
        for start, end in intervals:
            self.add(start, end)

    def __iter__(self) -> Iterator[Interval]:
        return iter(zip(self._starts, self._ends))

    def __len__(self) -> int:
        return len(self._starts)

    def __bool__(self) -> bool:
        return bool(self._starts)

    def __repr__(self) -> str:
        inner = ", ".join(f"[{s:%Y-%m-%d %H:%M}, {e:%Y-%m-%d %H:%M})" for s, e in self)
        return f"IntervalSet({inner})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IntervalSet):
            return NotImplemented
        return list(self) == list(other)

    def __contains__(self, instant: datetime) -> bool:
        i = bisect_right(self._starts, instant) - 1
        return i >= 0 and instant < self._ends[i]

    def copy(self) -> "IntervalSet":
        clone = IntervalSet()
        clone._starts = list(self._starts)
        clone._ends = list(self._ends)
        return clone

    def total(self) -> timedelta:
        """The total length of time in the set."""
        return sum((end - start for start, end in self), timedelta(0))

    def add(self, start: datetime, end: datetime) -> None:
        """Add [start, end) to the set, merging it with every interval it overlaps or touches."""
        if start >= end:
            return
        # The first stored interval that ends at or after `start` is the first candidate.
        i = bisect_right(self._ends, start)
        if i < len(self._starts) and self._starts[i] <= end:
            start = min(start, self._starts[i])
            end = max(end, self._ends[i])
            del self._starts[i]
            del self._ends[i]
        self._starts.insert(i, start)
        self._ends.insert(i, end)

    def remove(self, start: datetime, end: datetime) -> None:
        """Take [start, end) out of the set, splitting any interval that straddles it."""
        if start >= end:
            return
        i = bisect_right(self._ends, start)
        j = i
        new_starts: list[datetime] = []
        new_ends: list[datetime] = []
        while j < len(self._starts) and self._starts[j] < end:
            s, e = self._starts[j], self._ends[j]
            if s < start:
                new_starts.append(s)
                new_ends.append(start)
            elif e > end:
                new_starts.append(end)
                new_ends.append(e)
            j += 1
        self._starts[i:j] = new_starts
        self._ends[i:j] = new_ends

    def clip(self, start: datetime, end: datetime) -> "IntervalSet":
        """A new set holding the part of this one inside [start, end)."""
        result = IntervalSet()
        for s, e in self:
            s, e = max(s, start), min(e, end)
            if s < e:
                result._starts.append(s)
                result._ends.append(e)
        return result

    def intersection(self, other: "IntervalSet") -> "IntervalSet":
        """A new set holding the instants that are in both sets."""
        result = IntervalSet()
        a, b = list(self), list(other)
        i = j = 0
        while i < len(a) and j < len(b):
            s = max(a[i][0], b[j][0])
            e = min(a[i][1], b[j][1])
            if s < e:
                result._starts.append(s)
                result._ends.append(e)
            if a[i][1] <= b[j][1]:
                i += 1
            else:
                j += 1
        return result

    def gaps(self, start: datetime, end: datetime) -> "IntervalSet":
        """A new set holding the instants in [start, end) that are *not* in this set."""
        result = IntervalSet([(start, end)])
        for s, e in self:
            result.remove(s, e)
        return result
