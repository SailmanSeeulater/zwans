"""Totals over a list of entries."""

from collections import defaultdict
from datetime import date, timedelta

from timesheet.entries import Entry

WEEKLY_LIMIT = 40 * 60  # minutes before overtime starts


def minutes_by_project(entries: list[Entry]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for entry in entries:
        totals[entry.project] += entry.minutes
    return dict(sorted(totals.items()))


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())  # Monday


def minutes_by_week(entries: list[Entry]) -> dict[date, int]:
    totals: dict[date, int] = defaultdict(int)
    for entry in entries:
        totals[week_start(entry.day)] += entry.minutes
    return dict(sorted(totals.items()))


def overtime_by_week(entries: list[Entry], limit: int = WEEKLY_LIMIT) -> dict[date, int]:
    return {week: max(0, total - limit) for week, total in minutes_by_week(entries).items()}
