"""Sequential ids, one counter per kind of record, kept in the data file."""

from __future__ import annotations

PREFIXES = {
    "patient": "P",
    "appointment": "A",
    "series": "S",
    "reminder": "R",
    "waitlist": "W",
    "message": "M",
    "delivery": "D",
}


def next_id(counters: dict[str, int], kind: str) -> str:
    number = counters.get(kind, 0) + 1
    counters[kind] = number
    return f"{PREFIXES[kind]}{number:04d}"


def peek(counters: dict[str, int], kind: str) -> str:
    """The id `next_id` would hand out next, without using it up."""
    return f"{PREFIXES[kind]}{counters.get(kind, 0) + 1:04d}"
