"""Checks on user input. Each returns the cleaned value or raises ValidationError."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationError

KINDS = ("consult", "follow-up", "procedure", "review", "vaccination")
CHANNELS = ("sms", "email")

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_ROOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,15}$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ]{6,18}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def check_id(kind: str, value: str) -> str:
    if not _ID.match(value or ""):
        raise ValidationError(f"bad {kind} id {value!r}: lowercase letters, digits and dashes")
    return value


def check_room_id(value: str) -> str:
    if not _ROOM.match(value or ""):
        raise ValidationError(f"bad room id {value!r}")
    return value


def check_name(kind: str, value: str) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValidationError(f"a {kind} needs a name")
    if len(value) > 80:
        raise ValidationError(f"{kind} name too long: {value[:20]}...")
    return value


def check_zone(value: str) -> str:
    try:
        if not value:
            raise ValueError(value)
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError(
            f"unknown time zone {value!r}: expected an IANA name like Europe/London"
        ) from None
    return value


def check_phone(value: str) -> str:
    value = (value or "").strip()
    if value and not _PHONE.match(value):
        raise ValidationError(f"bad phone number {value!r}")
    return value


def check_email(value: str) -> str:
    value = (value or "").strip()
    if value and not _EMAIL.match(value):
        raise ValidationError(f"bad email address {value!r}")
    return value


def check_channel(value: str) -> str:
    if value not in CHANNELS:
        raise ValidationError(f"bad channel {value!r}: one of {', '.join(CHANNELS)}")
    return value


def check_kind(value: str) -> str:
    if value not in KINDS:
        raise ValidationError(f"bad appointment kind {value!r}: one of {', '.join(KINDS)}")
    return value


def check_minutes(value: int, grid: int, longest: int = 8 * 60) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"minutes must be a whole number, not {value!r}")
    if value <= 0 or value > longest:
        raise ValidationError(f"an appointment lasts 1 to {longest} minutes, not {value}")
    if value % grid:
        raise ValidationError(f"appointments last a multiple of {grid} minutes, not {value}")
    return value


def check_hours_list(value: object) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(h, int) and not isinstance(h, bool) and 0 < h <= 24 * 14 for h in value
    ):
        raise ValidationError(f"reminder hours must be a list of whole hours, not {value!r}")
    return sorted(set(value), reverse=True)
