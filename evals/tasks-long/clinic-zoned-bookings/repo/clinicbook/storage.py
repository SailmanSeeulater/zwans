"""The Store: every table in memory, loaded from and saved to one JSON file."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from . import serialize
from .config import Settings
from .errors import StorageError
from .migrations import CURRENT, upgrade
from .models import (
    Appointment,
    AuditEntry,
    Clinic,
    Clinician,
    Message,
    Patient,
    QueuedDelivery,
    Reminder,
    Room,
    Series,
    WaitlistEntry,
)

VERSION = CURRENT

_TABLES = (
    "clinics", "rooms", "clinicians", "patients", "appointments", "series", "reminders",
    "waitlist", "messages", "webhook_queue", "audit", "counters", "settings",
)


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.settings = Settings()
        self.counters: dict[str, int] = {}
        self.clinics: dict[str, Clinic] = {}
        self.rooms: dict[str, Room] = {}
        self.clinicians: dict[str, Clinician] = {}
        self.patients: dict[str, Patient] = {}
        self.appointments: dict[str, Appointment] = {}
        self.series: dict[str, Series] = {}
        self.reminders: dict[str, Reminder] = {}
        self.waitlist: dict[str, WaitlistEntry] = {}
        self.messages: list[Message] = []
        self.webhook_queue: list[QueuedDelivery] = []
        self.audit: list[AuditEntry] = []
        self.loaded_version: int | None = None
        self._on_reset: list[Callable[[], None]] = []

    # -- opening and saving -----------------------------------------------------------

    @classmethod
    def memory(cls) -> Store:
        return cls()

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> Store:
        path = Path(path)
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageError(f"{path} is not a clinicbook data file: {exc}") from None
        return cls.from_dict(data, path)

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> Store:
        if not isinstance(data, dict):
            raise StorageError("a data file holds a JSON object")
        store = cls(path)
        store.loaded_version = data.get("version", 0)
        try:
            serialize.load(store, upgrade(data))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"damaged data file: {exc!r}") from None
        return store

    def to_dict(self) -> dict[str, Any]:
        return serialize.dump(self, VERSION)

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise StorageError("this store has no file; give save() a path")
        text = json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        self.path = target
        return target

    # -- transactions -----------------------------------------------------------------

    def on_reset(self, callback: Callable[[], None]) -> None:
        """Called after a rollback replaced the tables, so derived indexes can rebuild."""
        self._on_reset.append(callback)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Store]:
        saved = {name: copy.deepcopy(getattr(self, name)) for name in _TABLES}
        try:
            yield self
        except BaseException:
            for name, value in saved.items():
                setattr(self, name, value)
            for callback in self._on_reset:
                callback()
            raise

    def replace_with(self, other: Store) -> None:
        """Take over every table of `other` (a restore)."""
        for name in _TABLES:
            setattr(self, name, getattr(other, name))
        for callback in self._on_reset:
            callback()

    def counts(self) -> dict[str, int]:
        return {
            name: len(getattr(self, name))
            for name in _TABLES
            if name not in ("counters", "settings")
        }
