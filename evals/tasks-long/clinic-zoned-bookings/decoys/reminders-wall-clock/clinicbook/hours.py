"""Opening hours: the times of day a clinic is open, weekday by weekday."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .errors import ValidationError
from .timeutil import WEEKDAYS, end_of, format_clock, minutes_of_day, parse_clock, weekday_key

DEFAULT_SPEC = {day: ["08:00-18:00"] for day in WEEKDAYS[:5]}


@dataclass(frozen=True, order=True)
class Interval:
    open: int  # minutes after midnight
    close: int  # may be 1440, i.e. open until midnight

    @classmethod
    def parse(cls, text: str) -> Interval:
        start, sep, end = text.partition("-")
        try:
            if not sep:
                raise ValueError(text)
            interval = cls(parse_clock(start), parse_clock(end))
        except ValueError:
            raise ValidationError(f"bad opening hours {text!r}: expected HH:MM-HH:MM") from None
        if interval.open >= interval.close:
            raise ValidationError(f"bad opening hours {text!r}: closes before it opens")
        return interval

    def contains(self, start: int, end: int) -> bool:
        return self.open <= start and end <= self.close

    def __str__(self) -> str:
        return f"{format_clock(self.open)}-{format_clock(self.close)}"


class OpeningHours:
    def __init__(self, week: dict[str, list[Interval]]) -> None:
        self._week = {day: sorted(week.get(day, [])) for day in WEEKDAYS}
        for day, intervals in self._week.items():
            for before, after in zip(intervals, intervals[1:]):
                if after.open < before.close:
                    raise ValidationError(f"opening hours overlap on {day}: {before} and {after}")

    @classmethod
    def parse(cls, spec: dict[str, object] | None) -> OpeningHours:
        """{"mon": "08:00-12:00, 13:00-18:00", "sat": ["09:00-12:00"], "sun": None}."""
        if spec is None:
            spec = DEFAULT_SPEC
        week: dict[str, list[Interval]] = {}
        for day, value in spec.items():
            if day not in WEEKDAYS:
                raise ValidationError(f"bad weekday {day!r}: one of {', '.join(WEEKDAYS)}")
            if value in (None, "", "closed"):
                parts: list[str] = []
            elif isinstance(value, str):
                parts = [p.strip() for p in value.split(",") if p.strip()]
            elif isinstance(value, list):
                parts = [str(p) for p in value]
            else:
                raise ValidationError(f"bad opening hours for {day}: {value!r}")
            week[day] = [Interval.parse(p) for p in parts]
        return cls(week)

    def to_spec(self) -> dict[str, list[str]]:
        return {day: [str(i) for i in ivs] for day, ivs in self._week.items() if ivs}

    def intervals(self, day: date) -> list[Interval]:
        return list(self._week[weekday_key(day)])

    def open_minutes(self, day: date) -> int:
        return sum(i.close - i.open for i in self.intervals(day))

    def covers(self, start: datetime, minutes: int) -> bool:
        """Whether an appointment starting at `start` sits inside one opening interval,
        judged by its local start and local end (`minutes` of real time later)."""
        begin = minutes_of_day(start)
        finish = end_of(start, minutes)
        end = (finish.date() - start.date()).days * 24 * 60 + minutes_of_day(finish)
        return any(i.contains(begin, end) for i in self.intervals(start.date()))

    def describe(self) -> list[str]:
        lines = []
        for day in WEEKDAYS:
            ivs = self._week[day]
            lines.append(f"{day}  {', '.join(str(i) for i in ivs) if ivs else 'closed'}")
        return lines

    def __eq__(self, other: object) -> bool:
        return isinstance(other, OpeningHours) and self._week == other._week

    def __repr__(self) -> str:
        return f"OpeningHours({self.to_spec()!r})"
