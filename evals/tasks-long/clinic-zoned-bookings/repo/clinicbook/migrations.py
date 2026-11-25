"""Bringing data files written by older releases up to the current format.

Each migration takes the dict of one version and returns the dict of the next. They run
in a chain on load, so a file from any older release ends up current; saving then writes
the current version.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .errors import StorageError
from .timeutil import WEEKDAYS, format_datetime, parse_datetime

CURRENT = 1

Migration = Callable[[dict[str, Any]], dict[str, Any]]
_MIGRATIONS: dict[int, Migration] = {}


def migration(from_version: int) -> Callable[[Migration], Migration]:
    def register(fn: Migration) -> Migration:
        _MIGRATIONS[from_version] = fn
        return fn

    return register


def version_of(data: dict[str, Any]) -> int:
    version = data.get("version", 0)
    if not isinstance(version, int) or version < 0:
        raise StorageError(f"bad data file version {version!r}")
    return version


def upgrade(data: dict[str, Any]) -> dict[str, Any]:
    """A copy of `data` in the current format."""
    version = version_of(data)
    if version > CURRENT:
        raise StorageError(
            f"this data file is version {version}, written by a newer clinicbook "
            f"(this one reads up to {CURRENT})"
        )
    data = copy.deepcopy(data)
    while version < CURRENT:
        data = _MIGRATIONS[version](data)
        version += 1
        data["version"] = version
    return data


def _days(text: str) -> list[str]:
    """0.x wrote the open days as a range, `mon-fri`, or a list, `mon,wed,fri`."""
    if "-" in text:
        first, _, last = text.partition("-")
        return list(WEEKDAYS[WEEKDAYS.index(first) : WEEKDAYS.index(last) + 1])
    return [d.strip() for d in text.split(",") if d.strip()]


@migration(0)
def _from_0x(data: dict[str, Any]) -> dict[str, Any]:
    """clinicbook 0.x: `bookings` instead of appointments, one clinic per clinician,
    one opening interval for a range of days, `next_ids` instead of counters."""
    clinics = []
    for row in data.get("clinics", []):
        hours = row.get("hours", "08:00-18:00")
        clinics.append(
            {
                "id": row["id"],
                "name": row["name"],
                "zone": row["zone"],
                "hours": {day: [hours] for day in _days(row.get("days", "mon-fri"))},
                "closures": {},
                "address": row.get("address", ""),
                "phone": row.get("phone", ""),
                "reminder_hours": None,
            }
        )
    clinicians = [
        {
            "id": row["id"],
            "name": row["name"],
            "clinics": [row["clinic"]],
            "specialty": row.get("specialty", ""),
            "active": True,
        }
        for row in data.get("clinicians", [])
    ]
    rooms = [
        {"id": row["id"], "clinic": row["clinic"], "name": row.get("name", row["id"]),
         "active": True}
        for row in data.get("rooms", [])
    ]
    patients = [
        {"id": row["id"], "name": row["name"], "phone": row.get("phone", ""),
         "email": row.get("email", ""), "channel": "sms" if row.get("phone") else "email"}
        for row in data.get("patients", [])
    ]
    appointments = [
        {
            "id": row["id"],
            "clinic": row["clinic"],
            "clinician": row["clinician"],
            "room": row["room"],
            "patient": row["patient"],
            "start": format_datetime(parse_datetime(row["when"])),
            "minutes": row["duration"],
            "kind": row.get("type", "consult"),
            "status": {"done": "completed", "dna": "no_show"}.get(row["state"], row["state"]),
            "series": None,
            "notes": row.get("notes", ""),
            "created": None,
            "source": "desk",
        }
        for row in data.get("bookings", [])
    ]
    reminders = [
        {
            "id": row["id"],
            "appointment": row["booking"],
            "hours_before": row["hours"],
            "due": format_datetime(parse_datetime(row["due"])),
            "sent": format_datetime(parse_datetime(row["sent"])) if row.get("sent") else None,
        }
        for row in data.get("reminders", [])
    ]
    counters = {
        {"booking": "appointment"}.get(kind, kind): n
        for kind, n in data.get("next_ids", {}).items()
    }
    return {
        "version": 1,
        "settings": {},
        "counters": counters,
        "clinics": clinics,
        "rooms": rooms,
        "clinicians": clinicians,
        "patients": patients,
        "appointments": appointments,
        "series": [],
        "reminders": reminders,
        "waitlist": [],
        "messages": [],
        "webhook_queue": [],
        "audit": [],
    }
