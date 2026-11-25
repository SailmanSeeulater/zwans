"""Time comes from a clock: a function returning an ISO-8601 UTC timestamp. Tests and
scripts pass their own; the CLI honours SHOPDESK_NOW."""

import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from shopdesk.errors import InvalidInput

Clock = Callable[[], str]

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_from_env(environ: Mapping[str, str] = os.environ) -> Clock:
    fixed = environ.get("SHOPDESK_NOW")
    if fixed:
        return lambda: fixed
    return utc_now


def day(stamp: str) -> str:
    """The date part of a timestamp."""
    return stamp[:10]


def parse_day(text: str) -> str:
    if not _DAY.match(text):
        raise InvalidInput(f"Dates look like 2026-03-01, not {text!r}.")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise InvalidInput(f"No such date: {text}") from None
    return text


def in_range(stamp: str, start: str | None, end: str | None) -> bool:
    """Whether the timestamp's date lies in [start, end], both inclusive and optional."""
    date = day(stamp)
    if start is not None and date < start:
        return False
    return not (end is not None and date > end)
