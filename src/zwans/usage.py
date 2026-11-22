"""What Zwans has used, over time: tokens and dollars by day, week, month and year.

A session's transcript records each model call's usage with the time it ended, so the
transcripts in Zwans's home are the ledger; nothing else is kept. When a session is deleted
its transcript goes, so its calls are copied to `usage-archive.jsonl` first and what was
spent stays counted. Subagents' calls are in their session's transcript. Eval runs and rooms
keep their own records and aren't counted here.

Dollars are worked out from today's prices (pricing.cost), as the rest of Zwans shows them.
A model on this machine costs nothing. A call on a model with no known price, such as a
hosted one the config gives no `prices` for, counts tokens and no dollars.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from zwans.events import UsageUpdated
from zwans.pricing import cost

TRANSCRIPTS = "transcripts"
ARCHIVE = "usage-archive.jsonl"
MARK = '"usage_updated"'  # a line without it isn't a call; most lines are streamed text

type Period = Literal["day", "week", "month", "year"]
PERIODS: tuple[Period, ...] = ("day", "week", "month", "year")
# How many of each the series goes back; years go back to the first call.
SPANS: dict[Period, int] = {"day": 30, "week": 12, "month": 12}
CALENDAR_WEEKS = 53  # the calendar of days: a year, in whole weeks starting on Monday


@dataclass(frozen=True)
class Call:
    """One model call."""

    time: datetime  # when it ended, with its timezone
    session: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    web_searches: int

    @property
    def dollars(self) -> float | None:
        return cost(
            UsageUpdated(
                model=self.model,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_read_tokens=self.cache_read_tokens,
                cache_write_tokens=self.cache_write_tokens,
                web_searches=self.web_searches,
            )
        )


@dataclass
class Total:
    """Usage added up over some calls."""

    calls: int = 0
    input_tokens: int = 0  # sent at the full input price
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    dollars: float = 0.0
    unpriced_calls: int = 0  # calls on a model with no known price: tokens, no dollars
    sessions: set[str] = field(default_factory=set, repr=False)

    def add(self, call: Call) -> None:
        self.calls += 1
        self.input_tokens += call.input_tokens
        self.output_tokens += call.output_tokens
        self.cache_read_tokens += call.cache_read_tokens
        self.cache_write_tokens += call.cache_write_tokens
        self.sessions.add(call.session)
        dollars = call.dollars
        if dollars is None:
            self.unpriced_calls += 1
        else:
            self.dollars += dollars

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["sessions"] = len(self.sessions)
        data["tokens"] = (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )
        return data


def _calls_in(lines: Iterable[str], session: str) -> Iterator[Call]:
    for line in lines:
        if MARK not in line:
            continue
        try:
            record = json.loads(line)
            if record.get("type") != "usage_updated":
                continue
            yield Call(
                time=datetime.fromisoformat(record["time"]),
                session=str(record.get("session") or session),
                model=str(record.get("model") or ""),
                input_tokens=int(record.get("input_tokens") or 0),
                output_tokens=int(record.get("output_tokens") or 0),
                cache_read_tokens=int(record.get("cache_read_tokens") or 0),
                cache_write_tokens=int(record.get("cache_write_tokens") or 0),
                web_searches=int(record.get("web_searches") or 0),
            )
        except (ValueError, KeyError, TypeError):
            continue  # a line cut short by a crash, or not a record at all


def _read(path: Path, session: str) -> list[Call]:
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            return list(_calls_in(lines, session))
    except OSError:
        return []


def read_calls(home: Path) -> list[Call]:
    """Every model call recorded in `home`: the saved sessions' and the deleted ones'."""
    calls = _read(home / ARCHIVE, "deleted")
    folder = home / TRANSCRIPTS
    if folder.is_dir():
        for path in sorted(folder.glob("*.jsonl")):
            calls.extend(_read(path, path.stem))
    return calls


def archive(home: Path, session_id: str) -> None:
    """Keep a session's usage before its transcript is deleted."""
    calls = _read(home / TRANSCRIPTS / f"{session_id}.jsonl", session_id)
    if not calls:
        return
    with (home / ARCHIVE).open("a", encoding="utf-8") as out:
        for call in calls:
            record = {
                "type": "usage_updated",
                **asdict(call),
                "time": call.time.isoformat(timespec="milliseconds"),
            }
            out.write(json.dumps(record) + "\n")


def bucket_start(day: date, period: Period) -> date:
    """The first day of the day, week (Monday), month or year `day` is in."""
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    if period == "year":
        return day.replace(month=1, day=1)
    return day


def _step_back(start: date, period: Period) -> date:
    """The start of the bucket before the one starting at `start`."""
    return bucket_start(start - timedelta(days=1), period)


def _calendar(dated: list[tuple[date, Call]], today: date) -> dict[str, Any]:
    """The last CALENDAR_WEEKS weeks, day by day, for a calendar of how much was used: where
    it starts (a Monday) and the days with any use, oldest first."""
    start = bucket_start(today, "week") - timedelta(weeks=CALENDAR_WEEKS - 1)
    days: dict[date, Total] = {}
    for day, call in dated:
        if start <= day <= today:
            days.setdefault(day, Total()).add(call)
    used = []
    for day in sorted(days):
        total = days[day].as_json()
        used.append(
            {
                "day": day.isoformat(),
                "tokens": total["tokens"],
                "dollars": total["dollars"],
                "calls": total["calls"],
                "sessions": total["sessions"],
            }
        )
    return {"start": start.isoformat(), "end": today.isoformat(), "days": used}


def summarize(calls: Iterable[Call], now: datetime) -> dict[str, Any]:
    """Totals for the current day, week, month and year and for all time, a series of
    buckets for each period, oldest first with empty ones included, and totals by model.
    Days are `now`'s timezone's: a call at 11pm counts for that evening, not for UTC's
    tomorrow."""
    zone = now.tzinfo
    today = now.date()
    dated = [(call.time.astimezone(zone).date(), call) for call in calls]
    first = min((day for day, _ in dated), default=today)

    series: dict[str, list[dict[str, Any]]] = {}
    current: dict[str, Total] = {}
    for period in PERIODS:
        newest = bucket_start(today, period)
        starts = [newest]
        wanted = SPANS.get(period)
        while (len(starts) < wanted) if wanted else (starts[-1] > bucket_start(first, period)):
            starts.append(_step_back(starts[-1], period))
        buckets = {start: Total() for start in starts}
        for day, call in dated:
            bucket = buckets.get(bucket_start(day, period))
            if bucket is not None:
                bucket.add(call)
        series[period] = [
            {"start": start.isoformat(), **buckets[start].as_json()} for start in reversed(starts)
        ]
        current[period] = buckets[newest]

    everything = Total()
    by_model: dict[str, Total] = {}
    for _, call in dated:
        everything.add(call)
        by_model.setdefault(call.model or "unknown", Total()).add(call)
    models = sorted(by_model.items(), key=lambda item: -item[1].as_json()["tokens"])
    return {
        "calendar": _calendar(dated, today),
        "now": now.isoformat(timespec="seconds"),
        "first": first.isoformat() if dated else None,
        "totals": {
            **{period: current[period].as_json() for period in PERIODS},
            "all": everything.as_json(),
        },
        "series": series,
        "models": [{"model": name, **total.as_json()} for name, total in models],
    }
