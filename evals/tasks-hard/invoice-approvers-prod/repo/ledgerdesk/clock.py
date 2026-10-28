"""Time in ledgerdesk.

Every instant inside ledgerdesk is a timezone-aware datetime in UTC. People's local times
only matter at the edges: when a rule talks about someone's working day, and when the CLI
prints something for a human.
"""

import re
from datetime import UTC, datetime, timedelta, timezone

OFFSET_RE = re.compile(r"([+-])(\d{2}):(\d{2})")


def now() -> datetime:
    """The current instant, in UTC."""
    return datetime.now(UTC)


def parse_instant(text: str) -> datetime:
    """Read an ISO 8601 date-time and return it in UTC.

    A trailing `Z` means UTC. Text without an offset, like `2025-03-01T09:00`, is taken to be
    UTC already; it is *not* read as anyone's local time.
    """
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_offset(text: str) -> timezone:
    """Turn `+01:00` or `-05:00` into a fixed timezone."""
    match = OFFSET_RE.fullmatch(text.strip())
    if not match:
        raise ValueError(f"bad UTC offset {text!r}")
    delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
    return timezone(delta if match[1] == "+" else -delta)


def local(instant: datetime, offset: str) -> datetime:
    """`instant` as wall-clock time at the given UTC offset."""
    return instant.astimezone(parse_offset(offset))


def describe(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
