"""Time handling.

leafwiki stores every timestamp as an ISO 8601 string in UTC with a trailing ``Z``
("2026-03-01T09:00:00Z"). A clock is any callable returning an aware ``datetime``; the
wiki takes one so tests (and the CLI, through ``LEAFWIKI_NOW``) can pin the time.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

Clock = Callable[[], datetime]

_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def system_clock() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def stamp(moment: datetime) -> str:
    """Format an aware datetime the way leafwiki stores it."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).strftime(_FORMAT)


def parse(text: str) -> datetime:
    """Read a stored timestamp back. Accepts a ``+00:00`` suffix as well as ``Z``."""
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def days_between(earlier: str, later: datetime) -> float:
    return (later - parse(earlier)) / timedelta(days=1)


def env_clock(variable: str = "LEAFWIKI_NOW") -> Clock:
    """A clock pinned to the time in an environment variable, if it is set."""
    pinned = os.environ.get(variable)
    if not pinned:
        return system_clock
    moment = parse(pinned)
    return lambda: moment


class SteppingClock:
    """Starts at a given time and moves forward a fixed step on every call.

    Handy for scripted demos and imports, where every revision should get its own time.
    """

    def __init__(self, start: datetime, step: timedelta = timedelta(minutes=1)) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now = current + self.step
        return current

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def rfc822(text: str) -> str:
    """A stored timestamp in the format RSS wants ("Sun, 01 Mar 2026 09:00:00 +0000")."""
    return parse(text).strftime("%a, %d %b %Y %H:%M:%S +0000")
