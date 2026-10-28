"""Timestamps and branch-local dates."""

from datetime import UTC, date, datetime, timedelta


class TimestampError(ValueError):
    pass


def parse_utc(text: str) -> datetime:
    """'2026-02-07T10:15:00Z' -> an aware datetime in UTC. Offsets other than Z are
    converted; a timestamp without any offset is refused, since we can't tell where
    it was taken."""
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TimestampError(f"not a timestamp: {text!r}") from exc
    if value.tzinfo is None:
        raise TimestampError(f"timestamp has no time zone: {text!r}")
    return value.astimezone(UTC)


def local_date(moment: datetime, utc_offset: timedelta) -> date:
    """The calendar day at a branch with the given UTC offset when `moment` happened."""
    if moment.tzinfo is None:
        raise TimestampError("local_date needs an aware datetime")
    return (moment.astimezone(UTC) + utc_offset).date()


def days_between(start: date, end: date) -> int:
    return (end - start).days


def format_day(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"
