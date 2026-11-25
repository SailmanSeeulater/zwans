"""Record ids: a short prefix naming the table, then a number ("c12", "d3", "tl40")."""

import re

PREFIXES = {
    "contacts": "c",
    "companies": "co",
    "deals": "d",
    "notes": "n",
    "tasks": "t",
    "emails": "e",
    "timeline": "tl",
    "subscriptions": "wh",
    "outbox": "ob",
}

_ID = re.compile(r"^([a-z]+)(\d+)$")


def split(record_id: str) -> tuple[str, int]:
    match = _ID.match(record_id)
    if not match:
        return record_id, 0
    return match.group(1), int(match.group(2))


def sort_key(record_id: str) -> tuple[str, int, str]:
    prefix, number = split(record_id)
    return prefix, number, record_id


def table_of(record_id: str) -> str | None:
    prefix, _ = split(record_id)
    for table, known in PREFIXES.items():
        if known == prefix:
            return table
    return None


def next_id(store, table: str) -> str:
    prefix = PREFIXES[table]
    highest = max((split(key)[1] for key in store.keys(table)), default=0)
    return f"{prefix}{highest + 1}"
