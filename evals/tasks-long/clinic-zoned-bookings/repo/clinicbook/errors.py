"""Exceptions raised by clinicbook. Everything derives from ClinicError."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class ClinicError(Exception):
    """Base class for every error clinicbook raises on purpose."""


class NotFound(ClinicError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"no {kind} {key!r}")
        self.kind = kind
        self.key = key


class ValidationError(ClinicError):
    """Bad input: a malformed id, phone number, opening hours, setting..."""


class BookingError(ClinicError):
    """A booking, reschedule or slot search that can't be done."""


class Conflict(BookingError):
    def __init__(self, clashes: Iterable[Any]) -> None:
        self.clashes = list(clashes)
        ids = ", ".join(a.id for a in self.clashes)
        super().__init__(f"clashes with {ids}")


class OutsideOpeningHours(BookingError):
    pass


class InvalidTime(BookingError):
    pass


class StatusError(BookingError):
    """The appointment is in the wrong state for this (e.g. cancelling a completed one)."""


class StorageError(ClinicError):
    pass


class BackupError(ClinicError):
    pass


class ImportFailed(ClinicError):
    pass
