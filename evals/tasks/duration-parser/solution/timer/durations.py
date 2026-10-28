"""Parsing and formatting durations like "1h30m". The format is described in the README."""

import re

UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


class DurationError(ValueError):
    """Text that is not a valid duration."""


_COMPONENT = re.compile(r"\s*([0-9]+)([a-zA-Z])")


def parse_duration(text: str) -> int:
    """Return the number of seconds in a duration such as "1h30m"."""
    body = text.strip()
    if not body:
        raise DurationError("empty duration")
    order = list(UNITS)
    total = 0
    last = -1
    position = 0
    while position < len(body):
        match = _COMPONENT.match(body, position)
        if match is None:
            raise DurationError(f"not a duration: {text!r}")
        number, unit = match.group(1), match.group(2).lower()
        if unit not in UNITS:
            raise DurationError(f"unknown unit {unit!r} in {text!r}")
        rank = order.index(unit)
        if rank <= last:
            raise DurationError(f"units out of order or repeated in {text!r}")
        last = rank
        total += int(number) * UNITS[unit]
        position = match.end()
    return total


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
