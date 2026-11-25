"""The records. Each is a dataclass that turns into a plain dict (a row) for the store and
back; `from_row` ignores keys it doesn't know and fills missing ones with their defaults,
so rows written by older releases (fewer keys) and newer ones (more keys) both load."""

import copy
from dataclasses import MISSING, asdict, dataclass, field, fields
from typing import Any, Self

from orbit.text import display_name

STATUSES = ("active", "archived")
STAGES = ("lead", "qualified", "proposal", "negotiation", "won", "lost")
OPEN_STAGES = STAGES[:4]
CLOSED_STAGES = ("won", "lost")
DIRECTIONS = ("in", "out")
FIELD_TYPES = ("text", "number", "date", "choice", "multi")


class Record:
    def to_row(self) -> dict:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_row(cls, row: dict) -> Self:
        values = {}
        for spec in fields(cls):  # type: ignore[arg-type]
            if spec.name in row:
                values[spec.name] = copy.deepcopy(row[spec.name])
            elif spec.default is MISSING and spec.default_factory is MISSING:
                raise KeyError(f"{cls.__name__} row without {spec.name!r}")
        return cls(**values)

    def copy(self) -> Self:
        return copy.deepcopy(self)


@dataclass
class Contact(Record):
    id: str
    first_name: str
    last_name: str = ""
    emails: list[str] = field(default_factory=list)  # the first one is the primary address
    phones: list[str] = field(default_factory=list)
    company_id: str | None = None
    title: str = ""
    owner: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)  # sorted, no repeats
    fields: dict[str, Any] = field(default_factory=dict)  # custom field name -> value
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    last_contacted_at: str | None = None

    @property
    def name(self) -> str:
        return display_name(self.first_name, self.last_name) or (
            self.emails[0] if self.emails else self.id
        )

    @property
    def primary_email(self) -> str | None:
        return self.emails[0] if self.emails else None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class Company(Record):
    id: str
    name: str
    domain: str = ""
    primary_contact_id: str | None = None
    created_at: str = ""


@dataclass
class StageChange(Record):
    stage: str
    at: str
    contact_id: str | None = None  # whom the move came out of talking to, if anyone


@dataclass
class Deal(Record):
    id: str
    title: str
    amount: int = 0  # in cents
    stage: str = "lead"
    contact_ids: list[str] = field(default_factory=list)  # the first one is the main contact
    company_id: str | None = None
    owner: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None
    stage_history: list[dict] = field(default_factory=list)  # StageChange rows, oldest first

    @property
    def is_open(self) -> bool:
        return self.stage in OPEN_STAGES

    def history(self) -> list[StageChange]:
        return [StageChange.from_row(row) for row in self.stage_history]


@dataclass
class Note(Record):
    id: str
    contact_id: str
    body: str
    at: str = ""
    author: str = ""


@dataclass
class Task(Record):
    id: str
    contact_id: str
    title: str
    due: str | None = None  # a date, "2026-03-04"
    owner: str = ""
    done: bool = False
    done_at: str | None = None
    created_at: str = ""


@dataclass
class Email(Record):
    id: str
    contact_id: str
    subject: str
    direction: str = "out"
    address: str = ""  # the address it went to or came from
    at: str = ""


@dataclass
class TimelineEntry(Record):
    id: str
    at: str
    contact_id: str
    contact_name: str  # kept on the entry so listing a timeline needs no lookups
    kind: str  # created, updated, note, email, task, task-done, deal, stage
    summary: str
    ref: str | None = None  # the note, task, email or deal the entry is about


@dataclass
class FieldDef(Record):
    id: str  # the field's name, which is also its key in Contact.fields
    type: str = "text"
    label: str = ""
    choices: list[str] = field(default_factory=list)  # for choice and multi fields

    @property
    def name(self) -> str:
        return self.id


@dataclass
class Subscription(Record):
    id: str
    url: str
    events: list[str] = field(default_factory=lambda: ["*"])
    contact_id: str | None = None  # only events about this contact
    secret: str = ""
    active: bool = True
    created_at: str = ""

    def wants(self, event: str) -> bool:
        return self.active and ("*" in self.events or event in self.events)


@dataclass
class OutboxMessage(Record):
    id: str
    subscription_id: str
    event: str
    payload: dict
    created_at: str = ""
    attempts: int = 0
    next_attempt_at: str | None = None
    delivered_at: str | None = None
    failed: bool = False
    last_error: str | None = None

    @property
    def pending(self) -> bool:
        return self.delivered_at is None and not self.failed
