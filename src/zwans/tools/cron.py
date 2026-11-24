"""The Cron tool: what a cron expression means, in words, and when it runs next.

Cron expressions are easy to get almost right: `0 9 * * 1-5` against `0 9 1-5 * *`, a step
that starts where you didn't expect, or the old rule that when both the day of the month and
the day of the week are given, a day matches if either does. A model writing a crontab line,
a GitHub Actions schedule or a Kubernetes CronJob can check it here instead of reasoning it
out: the expression comes back explained in plain English, with its next run times in a
time zone, worked out with the zone's daylight saving changes.

It's pure computation: nothing is run and nothing is read.
"""

import calendar
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

HORIZON_YEARS = 30  # how far ahead to look for a run before saying it never comes
MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
MONTH_NAMES = ["", *list(calendar.month_name)[1:]]
WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@dataclass(frozen=True)
class Unit:
    name: str
    plural: str
    low: int
    high: int
    names: tuple[str, ...] = ()  # spelled values, the first standing for `low`


SECOND = Unit("second", "seconds", 0, 59)
MINUTE = Unit("minute", "minutes", 0, 59)
HOUR = Unit("hour", "hours", 0, 23)
DAY = Unit("day of the month", "days of the month", 1, 31)
MONTH = Unit("month", "months", 1, 12, tuple(MONTHS))
WEEKDAY = Unit("day of the week", "days of the week", 0, 7, tuple(WEEKDAYS))


@dataclass(frozen=True)
class Item:
    kind: str  # "all" (* or */n), "one" (5), "range" (1-5, 1-5/2, or 10/5, which runs to the end)
    start: int
    end: int
    step: int = 1


@dataclass(frozen=True)
class CronField:
    unit: Unit
    text: str
    items: tuple[Item, ...]
    values: tuple[int, ...]  # sorted
    star: bool  # written starting with * (or ?): the day rule treats it as unrestricted


@dataclass(frozen=True)
class Schedule:
    seconds: CronField | None  # only with a sixth field
    minute: CronField
    hour: CronField
    day: CronField
    month: CronField
    weekday: CronField

    def day_matches(self, day: date) -> bool:
        in_month = day.day in self.day.values
        in_week = day.isoweekday() % 7 in self.weekday.values
        if self.day.star or self.weekday.star:
            return in_month and in_week
        return in_month or in_week  # both restricted: either will do


class CronInput(BaseModel):
    expression: str = Field(
        description='The cron expression: five fields ("30 9 * * 1-5"), six with seconds '
        'first, or a macro such as "@daily".'
    )
    count: int = Field(default=5, ge=1, le=20, description="How many next run times to list.")
    timezone: str = Field(
        default="",
        description='The time zone to work in, as an IANA name ("Europe/Amsterdam", "UTC"). '
        "Leave it empty for this machine's. GitHub Actions schedules run in UTC.",
    )
    after: str = Field(
        default="",
        description='List runs after this time instead of now, as "2027-01-01T00:00" (taken '
        "in the time zone unless it carries an offset).",
    )


class CronTool:
    name = "Cron"
    description = (
        "Explain a cron expression in plain English and list its next run times, worked out "
        "with daylight saving changes. Takes five fields, six with seconds first, macros "
        "such as @daily, names (JAN, MON), lists, ranges and steps. Use it to check a "
        "crontab line, a Kubernetes CronJob or a GitHub Actions schedule before relying on "
        "it; note that GitHub Actions schedules run in UTC, so pass timezone UTC for those."
    )
    input_model = CronInput
    read_only = True

    async def run(self, args: CronInput, ctx: ToolContext) -> ToolOutput:
        expression = " ".join(args.expression.split())
        schedule, expanded = parse(expression)
        zone, zone_name = time_zone(args.timezone.strip())
        start = _start(args.after.strip(), zone)
        runs, gaps = next_runs(schedule, zone, start, args.count)
        title = expression if expanded == expression else f"{expression} (= {expanded})"
        lines = [title, explain(schedule) + "."]
        shown_start = start.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z")
        if not runs:
            lines.append(
                f"\nIt never runs: no date in the next {HORIZON_YEARS} years matches (a day "
                "that no month in it has, such as the 31st of a 30-day month)."
            )
            return ToolOutput(content="\n".join(lines))
        lines.append(f"\nNext {len(runs)} runs in {zone_name} (after {shown_start}):")
        form = "%a %Y-%m-%d %H:%M:%S %Z" if schedule.seconds else "%a %Y-%m-%d %H:%M %Z"
        for run in runs:
            local = run.astimezone(zone)
            lines.append(f"  {local.strftime(form):<28}  in {_duration(run - start)}")
        for gap in gaps:
            lines.append(
                f"(No run at {gap:%Y-%m-%d %H:%M}: that time doesn't exist in {zone_name}, as "
                "the clocks jump forward. Some cron daemons run it just after the jump, "
                "others skip it.)"
            )
        if not args.timezone.strip():
            lines.append("(GitHub Actions schedules run in UTC: pass timezone UTC for those.)")
        return ToolOutput(content="\n".join(lines))


# -- parsing


def parse(expression: str) -> tuple[Schedule, str]:
    """The schedule, and the expression with a macro written out."""
    if not expression:
        raise ToolError("The expression is empty.")
    if expression.startswith("@"):
        if expression.lower() == "@reboot":
            raise ToolError("@reboot runs once when the machine starts, so it has no schedule.")
        if expression.lower() not in MACROS:
            known = ", ".join(MACROS)
            raise ToolError(f"{expression} isn't a cron macro. These are: {known}.")
        expanded = MACROS[expression.lower()]
    else:
        expanded = expression
    fields = expanded.split()
    if len(fields) not in (5, 6):
        raise ToolError(
            f"A cron expression has 5 fields (minute hour day-of-month month day-of-week), or "
            f"6 with seconds first; this one has {len(fields)}."
        )
    try:
        seconds = _field(fields.pop(0), SECOND) if len(fields) == 6 else None
        minute, hour, day, month, weekday = (
            _field(text, unit)
            for text, unit in zip(fields, (MINUTE, HOUR, DAY, MONTH, WEEKDAY), strict=True)
        )
    except ToolError as exc:
        if len(expanded.split()) == 6:
            raise ToolError(
                f"{exc} With six fields the first is seconds (a year field isn't supported)."
            ) from exc
        raise
    return Schedule(seconds, minute, hour, day, month, weekday), expanded


def _field(text: str, unit: Unit) -> CronField:
    items: list[Item] = []
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise ToolError(f"The {unit.name} field {text!r} has an empty item in its list.")
        base, slash, step_text = part.partition("/")
        step = 1
        if slash:
            if not step_text.isdigit() or int(step_text) == 0:
                raise ToolError(
                    f"The {unit.name} field {text!r} has a step {step_text!r}: a step is a "
                    "whole number above 0, as */15."
                )
            step = int(step_text)
        if base in ("*", "?"):
            item = Item("all", unit.low, unit.high if unit is not WEEKDAY else 6, step)
        elif "-" in base:
            first, _, last = base.partition("-")
            start, end = _value(first, unit, text), _value(last, unit, text)
            if unit is WEEKDAY and end == 0 and start > 0:
                end = 7  # FRI-SUN
            if start > end:
                raise ToolError(
                    f"The {unit.name} field {text!r} has a range {base!r} that goes backwards; "
                    "write it as two parts of a list instead, as 22-23,0-2."
                )
            item = Item("range", start, end, step)
        else:
            start = _value(base, unit, text)
            item = Item("range", start, unit.high, step) if slash else Item("one", start, start)
        items.append(item)
        values.update(range(item.start, item.end + 1, item.step))
    if unit is WEEKDAY and 7 in values:
        values = (values - {7}) | {0}  # 7 is Sunday too
    return CronField(unit, text, tuple(items), tuple(sorted(values)), text[0] in "*?")


def _value(text: str, unit: Unit, field: str) -> int:
    if text.isdigit():
        value = int(text)
    elif text.upper() in unit.names:
        value = unit.names.index(text.upper()) + unit.low
    else:
        named = f", or a name such as {unit.names[0]}" if unit.names else ""
        special = " (L, W and # aren't supported)" if any(c in text for c in "LW#") else ""
        raise ToolError(
            f"The {unit.name} field {field!r} has {text!r}, which isn't a number{named}{special}."
        )
    if not unit.low <= value <= unit.high:
        raise ToolError(
            f"The {unit.name} field {field!r} has {value}, out of range: {unit.plural} go from "
            f"{unit.low} to {unit.high}."
        )
    return value


# -- time zones and run times


def time_zone(name: str) -> tuple[tzinfo, str]:
    if name:
        if name.upper() == "UTC":
            return UTC, "UTC"
        try:
            return ZoneInfo(name), name
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ToolError(
                f"{name!r} isn't a time zone name. Use an IANA name, as Europe/Amsterdam, "
                "America/New_York or UTC."
            ) from exc
    return local_zone()


def local_zone() -> tuple[tzinfo, str]:
    """This machine's time zone, by its IANA name where that can be found."""
    candidates = [os.environ.get("TZ", "").lstrip(":")]
    try:
        link = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in link:
            candidates.append(link.split("zoneinfo/", 1)[1])
    except OSError:
        pass
    for candidate in candidates:
        if candidate:
            try:
                return ZoneInfo(candidate), candidate
            except (ZoneInfoNotFoundError, ValueError):
                continue
    fixed = datetime.now().astimezone().tzinfo or UTC
    return fixed, f"this machine's time zone ({datetime.now(fixed).strftime('%Z')})"


def _start(after: str, zone: tzinfo) -> datetime:
    if not after:
        return datetime.now(UTC).replace(microsecond=0)
    try:
        moment = datetime.fromisoformat(after)
    except ValueError as exc:
        raise ToolError(
            f'after should be a date and time, as "2027-01-01T09:00", not {after!r}.'
        ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(UTC)


def next_runs(
    schedule: Schedule, zone: tzinfo, start: datetime, count: int
) -> tuple[list[datetime], list[datetime]]:
    """The next run times after `start`, in UTC, and the wall-clock times skipped on the way
    because the clocks jumped over them."""
    # Wildcard jobs run in both copies of an hour repeated as the clocks go back; jobs at a
    # fixed time run once, as Vixie cron does.
    both_folds = schedule.minute.star or schedule.hour.star
    # Starting a little early catches the second copy of a repeated hour.
    begin = start.astimezone(zone).replace(tzinfo=None) - timedelta(hours=3)
    found: list[datetime] = []
    gaps: list[datetime] = []
    enough_at: datetime | None = None
    for wall in _wall_times(schedule, begin):
        # Times from the next few hours of wall clock can still come earlier in real time.
        if enough_at is not None and wall > enough_at + timedelta(hours=3):
            break
        instants = _instants(wall, zone, both_folds)
        if not instants and wall.replace(tzinfo=zone) > start:
            gaps.append(wall)
        found += [instant for instant in instants if instant > start]
        if enough_at is None and len(found) >= count:
            enough_at = wall
    runs = sorted(set(found))[:count]
    if runs:
        gaps = [gap for gap in gaps if gap.replace(tzinfo=zone) < runs[-1]]
    return runs, gaps


def _wall_times(schedule: Schedule, begin: datetime) -> Iterator[datetime]:
    """Matching wall-clock times from `begin` on, skipping whole months, days and hours."""
    seconds = schedule.seconds.values if schedule.seconds else (0,)
    first = (begin.year, begin.month, begin.day, begin.hour, begin.minute, begin.second)
    for year in range(begin.year, begin.year + HORIZON_YEARS + 1):
        for month in schedule.month.values:
            if (year, month) < first[:2]:
                continue
            days = calendar.monthrange(year, month)[1]
            for day in range(1, days + 1):
                if (year, month, day) < first[:3] or not schedule.day_matches(
                    date(year, month, day)
                ):
                    continue
                for hour in schedule.hour.values:
                    if (year, month, day, hour) < first[:4]:
                        continue
                    for minute in schedule.minute.values:
                        if (year, month, day, hour, minute) < first[:5]:
                            continue
                        for second in seconds:
                            if (year, month, day, hour, minute, second) < first:
                                continue
                            yield datetime(year, month, day, hour, minute, second)


def _instants(wall: datetime, zone: tzinfo, both_folds: bool) -> list[datetime]:
    """The moments (in UTC) a wall-clock time stands for: none in a gap as the clocks jump
    forward, two in an hour repeated as they go back."""
    first = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if first.astimezone(zone).replace(tzinfo=None) != wall:
        return []
    second = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    return [first, second] if both_folds and second != first else [first]


def _duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rest = divmod(total, 86_400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {seconds}s" if seconds and total < 600 else f"{minutes}m"
    return f"{seconds}s"


# -- explaining


def explain(schedule: Schedule) -> str:
    text = _time_phrase(schedule)
    days = [_day_phrase(schedule), _month_phrase(schedule.month)]
    text += "".join(f" {part}" for part in days if part)
    return text[0].upper() + text[1:]


def _time_phrase(schedule: Schedule) -> str:
    seconds, minute, hour = schedule.seconds, schedule.minute, schedule.hour
    one_second = seconds is None or (_ones(seconds) is not None and len(seconds.values) == 1)
    minutes, hours = _ones(minute), _ones(hour)
    if one_second and minutes is not None and len(minutes) == 1 and hours and len(hours) <= 6:
        second = seconds.values[0] if seconds else 0
        return "at " + _join([_clock(h, minutes[0], second, seconds is not None) for h in hours])
    parts = []
    if seconds is not None and seconds.values != (0,):
        parts.append(_count_phrase(seconds))
        if minute.text not in ("*", "?"):
            parts.append(_count_phrase(minute))
    else:
        parts.append(_count_phrase(minute))
    text = ", ".join(parts)
    if hour.text not in ("*", "?"):
        text += " past " + _hour_phrase(hour)
    return text


def _ones(field: CronField) -> list[int] | None:
    """The values, when the field is only a list of single values."""
    if all(item.kind == "one" for item in field.items):
        return list(field.values)
    return None


def _clock(hour: int, minute: int, second: int, with_seconds: bool) -> str:
    return f"{hour:02d}:{minute:02d}:{second:02d}" if with_seconds else f"{hour:02d}:{minute:02d}"


def _count_phrase(field: CronField) -> str:
    """For seconds and minutes: "every minute", "every 15 minutes", "at minutes 0 and 30"."""
    unit = field.unit
    ones = _ones(field)
    if ones is not None:
        noun = unit.name if len(ones) == 1 else unit.plural
        return f"at {noun} {_join([str(v) for v in ones])}"
    if len(field.items) == 1:
        item = field.items[0]
        every = f"every {unit.name}" if item.step == 1 else f"every {item.step} {unit.plural}"
        if item.kind == "all":
            return every
        return f"{every} from {item.start} through {item.end}"
    return f"at {unit.plural} {_join([_item_text(item, field) for item in field.items])}"


def _hour_phrase(field: CronField) -> str:
    ones = _ones(field)
    if ones is not None:
        return f"hour {ones[0]}" if len(ones) == 1 else f"hours {_join([str(v) for v in ones])}"
    if len(field.items) == 1:
        item = field.items[0]
        every = "every hour" if item.step == 1 else f"every {_ordinal(item.step)} hour"
        return every if item.kind == "all" else f"{every} from {item.start} through {item.end}"
    return f"hours {_join([_item_text(item, field) for item in field.items])}"


def _day_phrase(schedule: Schedule) -> str:
    day, weekday = schedule.day, schedule.weekday
    in_month = "" if day.text in ("*", "?") else _days_of_month(day)
    in_week = "" if weekday.text in ("*", "?") else _days_of_week(weekday)
    if in_month and in_week:
        joiner = "and" if day.star or weekday.star else "or"
        return f"{in_month} {joiner} {in_week}"
    return in_month or in_week


def _days_of_month(field: CronField) -> str:
    ones = _ones(field)
    if ones is not None:
        noun = "day" if len(ones) == 1 else "days"
        return f"on {noun} {_join([str(v) for v in ones])} of the month"
    if len(field.items) == 1:
        item = field.items[0]
        if item.kind == "all":
            return f"on every {_ordinal(item.step)} day of the month"
        if item.step == 1:
            return f"on days {item.start} through {item.end} of the month"
        return f"on every {_ordinal(item.step)} day from {item.start} through {item.end}"
    return f"on days {_join([_item_text(item, field) for item in field.items])} of the month"


def _days_of_week(field: CronField) -> str:
    ones = _ones(field)
    if ones is not None:
        return "on " + _join([WEEKDAY_NAMES[v % 7] for v in sorted({v % 7 for v in ones})])
    if len(field.items) == 1:
        item = field.items[0]
        if item.kind == "all":
            return f"on every {_ordinal(item.step)} day of the week"
        span = f"{WEEKDAY_NAMES[item.start % 7]} through {WEEKDAY_NAMES[item.end % 7]}"
        return f"on {span}" if item.step == 1 else f"on every {_ordinal(item.step)} day from {span}"
    return "on " + _join([_item_text(item, field) for item in field.items])


def _month_phrase(field: CronField) -> str:
    if field.text in ("*", "?"):
        return ""
    ones = _ones(field)
    if ones is not None:
        return "in " + _join([MONTH_NAMES[v] for v in ones])
    if len(field.items) == 1:
        item = field.items[0]
        if item.kind == "all":
            return f"in every {_ordinal(item.step)} month"
        span = f"{MONTH_NAMES[item.start]} through {MONTH_NAMES[item.end]}"
        if item.step == 1:
            return f"in {span}"
        return f"in every {_ordinal(item.step)} month from {span}"
    return "in " + _join([_item_text(item, field) for item in field.items])


def _item_text(item: Item, field: CronField) -> str:
    def name(value: int) -> str:
        if field.unit is WEEKDAY:
            return WEEKDAY_NAMES[value % 7]
        if field.unit is MONTH:
            return MONTH_NAMES[value]
        return str(value)

    if item.kind == "one":
        return name(item.start)
    step = f"every {_ordinal(item.step)} " if item.step > 1 else ""
    if item.kind == "all":
        return f"{step or 'every '}{field.unit.name}"
    return f"{step}{'from ' if step else ''}{name(item.start)} through {name(item.end)}"


def _ordinal(number: int) -> str:
    suffix = (
        "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
