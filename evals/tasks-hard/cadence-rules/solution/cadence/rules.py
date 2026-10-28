"""Expanding cadence rules into dates. SPEC.md defines the rule language."""

import calendar
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta

from cadence.holidays import Holidays

WEEKDAYS = {name: i for i, name in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}
WEEKDAYS.update(
    {
        name: i
        for i, name in enumerate(
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        )
    }
)
MONTHS = {
    name: i + 1
    for i, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
ORDINALS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "last": -1}
UNITS = {
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "year": "year",
    "years": "year",
}
SEARCH_LIMIT = 3660  # days to look for a business day before giving up


class RuleError(ValueError):
    """A cadence rule that does not follow SPEC.md."""


@dataclass
class Rule:
    unit: str  # "day", "week", "month", "year" or "business"
    every: int = 1
    selectors: list[tuple] = field(default_factory=list)
    start: date | None = None
    until: date | None = None
    count: int | None = None
    exceptions: set[date] = field(default_factory=set)
    closed: str = "keep"


def _parse_date(text: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise RuleError(f"bad date {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise RuleError(f"no such date {text!r}") from None


def _number(text: str) -> int:
    if not re.fullmatch(r"\d+", text):
        raise RuleError(f"expected a number, got {text!r}")
    return int(text)


def _items(text: str) -> list[str]:
    items = [item.strip() for item in text.split(",")]
    if any(not item for item in items):
        raise RuleError("empty item in a list")
    return items


def _week_selectors(text: str) -> list[tuple]:
    selectors = []
    for item in _items(text):
        if item not in WEEKDAYS:
            raise RuleError(f"not a weekday: {item!r}")
        selectors.append(("weekday", WEEKDAYS[item]))
    return selectors


def _month_selectors(text: str) -> list[tuple]:
    selectors = []
    for item in _items(text):
        words = item.split(" ")
        if len(words) == 2 and words[0] == "day":
            match = re.fullmatch(r"(-?)(\d+)", words[1])
            if not match or not 1 <= int(match[2]) <= 31:
                raise RuleError(f"bad day {item!r}")
            selectors.append(("day", -int(match[2]) if match[1] else int(match[2])))
        elif len(words) == 3 and words[:2] == ["business", "day"]:
            match = re.fullmatch(r"(-?)(\d+)", words[2])
            if not match or int(match[2]) < 1:
                raise RuleError(f"bad business day {item!r}")
            selectors.append(("business", -int(match[2]) if match[1] else int(match[2])))
        elif len(words) == 2 and words[0] in ORDINALS and words[1] in WEEKDAYS:
            selectors.append(("nth", ORDINALS[words[0]], WEEKDAYS[words[1]]))
        else:
            raise RuleError(f"bad day of the month {item!r}")
    return selectors


def _year_selectors(text: str) -> list[tuple]:
    selectors = []
    for item in _items(text):
        words = item.split(" ")
        if len(words) != 2 or words[0] not in MONTHS:
            raise RuleError(f"bad day of the year {item!r}")
        month, day = MONTHS[words[0]], _number(words[1])
        if not 1 <= day <= calendar.monthrange(2024, month)[1]:
            raise RuleError(f"no such day {item!r}")
        selectors.append(("yearday", month, day))
    return selectors


def _pattern(clause: str, rule: Rule) -> None:
    head, on, rest = clause.partition(" on ")
    if not on and clause.endswith(" on"):
        raise RuleError("nothing after 'on'")
    words = head.split(" ")
    if words == ["every", "business", "day"]:
        rule.unit = "business"
    elif words == ["daily"]:
        rule.unit = "day"
    elif words in (["weekly"], ["monthly"], ["yearly"]):
        rule.unit = {"weekly": "week", "monthly": "month", "yearly": "year"}[words[0]]
    elif len(words) == 3 and words[0] == "every" and words[2] in UNITS:
        rule.unit = UNITS[words[2]]
        rule.every = _number(words[1])
        if rule.every < 1:
            raise RuleError("the interval must be at least 1")
    else:
        raise RuleError(f"unknown pattern {clause!r}")
    if not on:
        return
    if rule.unit in ("day", "business"):
        raise RuleError("this pattern takes no 'on' part")
    parse = {"week": _week_selectors, "month": _month_selectors, "year": _year_selectors}
    rule.selectors = parse[rule.unit](rest)


def parse(text: str) -> Rule:
    clauses = [" ".join(clause.split()) for clause in text.lower().split(";")]
    if any(not clause for clause in clauses):
        raise RuleError("empty clause")
    rule = Rule(unit="day")
    _pattern(clauses[0], rule)
    seen = set()
    for clause in clauses[1:]:
        if clause.startswith("closed:"):
            key, value = "closed", clause[len("closed:") :].strip()
        else:
            key, _, value = clause.partition(" ")
        if key in seen:
            raise RuleError(f"{key} given twice")
        seen.add(key)
        if key == "from":
            rule.start = _parse_date(value)
        elif key == "until":
            rule.until = _parse_date(value)
        elif key == "count":
            rule.count = _number(value)
            if rule.count < 1:
                raise RuleError("count must be at least 1")
        elif key == "except":
            rule.exceptions = {_parse_date(item) for item in _items(value)}
        elif key == "closed":
            if value not in ("keep", "skip", "next", "previous"):
                raise RuleError(f"unknown closed-day policy {value!r}")
            rule.closed = value
        else:
            raise RuleError(f"unknown option {clause!r}")
    if rule.until is not None and rule.count is not None:
        raise RuleError("until and count cannot both be given")
    if rule.until is not None and rule.start is not None and rule.until < rule.start:
        raise RuleError("until is before from")
    return rule


class _Calendar:
    def __init__(self, holidays: Holidays | Iterable[date]):
        self.holidays = holidays if isinstance(holidays, Holidays) else Holidays(holidays)

    def is_business(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def step(self, day: date, direction: int) -> date:
        for _ in range(SEARCH_LIMIT):
            day += timedelta(days=direction)
            if self.is_business(day):
                return day
        raise RuleError("no business day found")


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _month_dates(rule: Rule, year: int, month: int, cal: _Calendar) -> set[date]:
    length = calendar.monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, length + 1)]
    result = set()
    for selector in rule.selectors:
        if selector[0] == "day":
            n = selector[1]
            result.add(date(year, month, min(n, length) if n > 0 else max(length + 1 + n, 1)))
        elif selector[0] == "nth":
            matches = [d for d in days if d.weekday() == selector[2]]
            index = selector[1]
            if index == -1:
                result.add(matches[-1])
            elif index <= len(matches):
                result.add(matches[index - 1])
        else:
            business = [d for d in days if cal.is_business(d)]
            n = selector[1]
            if abs(n) <= len(business):
                result.add(business[n - 1] if n > 0 else business[n])
    return result


def _scheduled(rule: Rule, anchor: date, horizon: date, cal: _Calendar) -> Iterator[date]:
    """Scheduled dates from the anchor on, in order, up to about the horizon."""
    if rule.unit == "day":
        day = anchor
        while day <= horizon:
            yield day
            day += timedelta(days=rule.every)
        return
    if rule.unit == "business":
        day = anchor
        while day <= horizon:
            if cal.is_business(day):
                yield day
            day += timedelta(days=1)
        return
    period = 0
    while True:
        if rule.unit == "week":
            monday = anchor - timedelta(days=anchor.weekday()) + timedelta(weeks=period)
            weekdays = [s[1] for s in rule.selectors] or [anchor.weekday()]
            dates = {monday + timedelta(days=w) for w in weekdays}
        elif rule.unit == "month":
            year, month = _add_months(anchor.year, anchor.month, period)
            if not rule.selectors:
                rule.selectors = [("day", anchor.day)]
            dates = _month_dates(rule, year, month, cal)
        else:
            year = anchor.year + period
            selectors = rule.selectors or [("yearday", anchor.month, anchor.day)]
            dates = set()
            for _, month, day in selectors:
                dates.add(date(year, month, min(day, calendar.monthrange(year, month)[1])))
        for day in sorted(dates):
            if day >= anchor:
                yield day
        if dates and min(dates) > horizon:
            return
        if not dates and rule.unit == "month" and date(year, month, 1) > horizon:
            return
        period += rule.every


def expand(
    rule: str, start: date, end: date, holidays: Holidays | Iterable[date] = ()
) -> list[date]:
    """The dates of the rule's occurrences from start to end, both inclusive."""
    parsed = parse(rule)
    if start > end:
        return []
    cal = _Calendar(holidays)
    anchor = parsed.start or start
    result: list[date] = []
    produced: list[date] = []  # every final date so far, for `count`
    horizon = end + timedelta(days=SEARCH_LIMIT)
    if parsed.until is not None:
        horizon = min(horizon, parsed.until)
    for scheduled in _scheduled(parsed, anchor, horizon, cal):
        if parsed.until is not None and scheduled > parsed.until:
            break
        if parsed.closed != "previous" and scheduled > end:
            break
        if scheduled in parsed.exceptions:
            continue
        final = scheduled
        if not cal.is_business(scheduled):
            if parsed.closed == "skip":
                continue
            if parsed.closed == "next":
                final = cal.step(scheduled, 1)
            elif parsed.closed == "previous":
                final = cal.step(scheduled, -1)
        if final > end:
            break
        if produced and produced[-1] == final:
            continue
        produced.append(final)
        if parsed.count is not None and len(produced) > parsed.count:
            break
        if final >= start:
            result.append(final)
    return result
