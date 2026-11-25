"""The wording of the messages sent to patients."""

from __future__ import annotations

import string

TEMPLATES = {
    "confirmation": "{patient}, your {kind} with {clinician} at {clinic} is booked for {when}.",
    "reminder": "Reminder: your {kind} with {clinician} at {clinic} is on {when}.",
    "cancellation": "{patient}, your {kind} at {clinic} on {when} has been cancelled.",
    "rescheduled": "{patient}, your {kind} at {clinic} has moved to {when}.",
    "waitlist_offer": (
        "{patient}, a place has come up at {clinic}: {when} with {clinician}. "
        "Call {phone} if you can't make it."
    ),
}


def fields_of(name: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(TEMPLATES[name]) if f}


def render(name: str, **values: str) -> str:
    missing = fields_of(name) - values.keys()
    if missing:
        raise KeyError(f"template {name!r} needs {', '.join(sorted(missing))}")
    return TEMPLATES[name].format(**values)
