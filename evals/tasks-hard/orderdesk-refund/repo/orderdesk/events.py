"""Domain events: the facts orderdesk records. The event log is the only source of truth.

Every event type is registered under a stable name with @event. That name is what is
written to the log, so an event type is never renamed or removed once it has shipped;
old logs must keep loading.

Events carry plain data only (str, int, tuples of Line), so they serialise to JSON with
to_record() and come back with from_record().
"""

from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar

EVENT_TYPES: dict[str, type["Event"]] = {}


def event(name: str):
    """Register an event class under the name it is stored as."""

    def register(cls: type["Event"]) -> type["Event"]:
        if name in EVENT_TYPES:
            raise ValueError(f"event type {name!r} is registered twice")
        cls.type = name
        EVENT_TYPES[name] = cls
        return cls

    return register


@dataclass(frozen=True)
class Event:
    type: ClassVar[str] = ""

    order_id: str
    at: str  # when it happened: ISO 8601, UTC, e.g. "2026-03-01T09:30:00Z"

    @property
    def day(self) -> str:
        """The calendar day (UTC) the event happened on, e.g. '2026-03-01'."""
        return self.at[:10]

    def to_fields(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_fields(cls, data: dict[str, Any]) -> "Event":
        return cls(**data)


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int
    unit_cents: int

    @property
    def total_cents(self) -> int:
        return self.qty * self.unit_cents


@event("order.placed")
@dataclass(frozen=True)
class OrderPlaced(Event):
    customer: str
    email: str
    lines: tuple[Line, ...]

    @property
    def total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    def to_fields(self) -> dict[str, Any]:
        data = super().to_fields()
        data["lines"] = [asdict(line) for line in self.lines]
        return data

    @classmethod
    def from_fields(cls, data: dict[str, Any]) -> "Event":
        lines = tuple(Line(**line) for line in data["lines"])
        return cls(**{**data, "lines": lines})


@event("payment.captured")
@dataclass(frozen=True)
class PaymentCaptured(Event):
    amount_cents: int
    method: str


@event("order.shipped")
@dataclass(frozen=True)
class OrderShipped(Event):
    carrier: str
    tracking: str


@event("order.cancelled")
@dataclass(frozen=True)
class OrderCancelled(Event):
    reason: str
    refund_cents: int  # what went back to the customer when the order was cancelled


@event("note.added")
@dataclass(frozen=True)
class NoteAdded(Event):
    author: str
    text: str


def to_record(ev: Event) -> dict[str, Any]:
    return {"type": ev.type, **ev.to_fields()}


def from_record(record: dict[str, Any]) -> Event:
    data = dict(record)
    name = data.pop("type")
    try:
        cls = EVENT_TYPES[name]
    except KeyError:
        raise ValueError(f"unknown event type {name!r}") from None
    return cls.from_fields(data)
