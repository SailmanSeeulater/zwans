"""Parsing and formatting durations like "1h30m". The format is described in the README."""

UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


class DurationError(ValueError):
    """Text that is not a valid duration."""


def parse_duration(text: str) -> int:
    """Return the number of seconds in a duration such as "1h30m"."""
    raise NotImplementedError


def format_duration(seconds: int) -> str:
    """Write a number of seconds the short way, largest unit first: 5400 -> "1h30m"."""
    if seconds < 0:
        raise ValueError("a duration cannot be negative")
    if seconds == 0:
        return "0s"
    parts = []
    for unit, size in UNITS.items():
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)
