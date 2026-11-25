"""The records deskline keeps.

Each record is a dataclass with ``to_dict``/``from_dict`` for the store. ``from_dict``
fills defaults for keys that older files may lack.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ROLES = ("viewer", "agent", "lead", "admin")
STATUSES = ("new", "open", "pending", "solved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")

# Which status changes the ticket workflow allows. "closed" is final; a solved ticket
# reopens when the customer writes again.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("open", "pending", "solved"),
    "open": ("pending", "solved"),
    "pending": ("open", "solved"),
    "solved": ("open", "closed"),
    "closed": (),
}


@dataclass
class Customer:
    id: str
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    organization: str = ""
    created_at: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Customer:
        return cls(
            id=data["id"],
            name=data["name"],
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            address=data.get("address", ""),
            organization=data.get("organization", ""),
            created_at=data.get("created_at", ""),
            tags=list(data.get("tags", [])),
        )


@dataclass
class Agent:
    id: str
    name: str
    email: str
    active: bool = True
    teams: list[str] = field(default_factory=list)
    signature: str = ""
    role: str = "agent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Agent:
        return cls(
            id=data["id"],
            name=data["name"],
            email=data.get("email", ""),
            active=data.get("active", True),
            teams=list(data.get("teams", [])),
            signature=data.get("signature", ""),
            role=data.get("role") or "agent",
        )


@dataclass
class Team:
    id: str
    name: str
    members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Team:
        return cls(id=data["id"], name=data["name"], members=list(data.get("members", [])))


@dataclass
class Queue:
    id: str
    name: str
    team: str | None = None
    default_priority: str = "normal"
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Queue:
        return cls(
            id=data["id"],
            name=data["name"],
            team=data.get("team"),
            default_priority=data.get("default_priority", "normal"),
            keywords=list(data.get("keywords", [])),
        )


@dataclass
class Comment:
    id: int
    author_kind: str  # "agent", "customer" or "system"
    author: str  # agent id, customer id or "system"
    body: str
    public: bool
    created_at: str
    via: str = "web"  # web, email, api, macro, merge
    from_address: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Comment:
        return cls(
            id=data["id"],
            author_kind=data["author_kind"],
            author=data["author"],
            body=data["body"],
            public=data.get("public", True),
            created_at=data["created_at"],
            via=data.get("via", "web"),
            from_address=data.get("from_address", ""),
        )


@dataclass
class Ticket:
    id: str
    subject: str
    customer_id: str
    status: str = "new"
    priority: str = "normal"
    queue: str = "general"
    assignee: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    first_response_at: str | None = None
    solved_at: str | None = None
    closed_at: str | None = None
    merged_into: str | None = None
    due_first_response: str | None = None
    due_resolution: str | None = None
    breaches: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status in ("new", "open", "pending")

    def public_comments(self) -> list[Comment]:
        return [c for c in self.comments if c.public]

    def next_comment_id(self) -> int:
        return max((c.id for c in self.comments), default=0) + 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["comments"] = [c.to_dict() for c in self.comments]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Ticket:
        return cls(
            id=data["id"],
            subject=data["subject"],
            customer_id=data["customer_id"],
            status=data.get("status", "new"),
            priority=data.get("priority", "normal"),
            queue=data.get("queue", "general"),
            assignee=data.get("assignee"),
            tags=list(data.get("tags", [])),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            first_response_at=data.get("first_response_at"),
            solved_at=data.get("solved_at"),
            closed_at=data.get("closed_at"),
            merged_into=data.get("merged_into"),
            due_first_response=data.get("due_first_response"),
            due_resolution=data.get("due_resolution"),
            breaches=list(data.get("breaches", [])),
            comments=[Comment.from_dict(c) for c in data.get("comments", [])],
        )


MACRO_ACTIONS = (
    "set_status",
    "set_priority",
    "set_queue",
    "add_tag",
    "remove_tag",
    "assign",
    "assign_self",
    "reply",
    "note",
)


@dataclass
class Macro:
    id: str
    name: str
    actions: list[dict[str, str]] = field(default_factory=list)
    created_by: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Macro:
        return cls(
            id=data["id"],
            name=data["name"],
            actions=[dict(a) for a in data.get("actions", [])],
            created_by=data.get("created_by", "system"),
        )


@dataclass
class SavedSearch:
    id: str
    name: str
    query: str
    owner: str
    shared: bool = False
    sort: str = "updated"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SavedSearch:
        return cls(
            id=data["id"],
            name=data["name"],
            query=data["query"],
            owner=data["owner"],
            shared=data.get("shared", False),
            sort=data.get("sort", "updated"),
        )


@dataclass
class SlaPolicy:
    priority: str
    first_response_minutes: int
    resolution_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlaPolicy:
        return cls(
            priority=data["priority"],
            first_response_minutes=int(data["first_response_minutes"]),
            resolution_minutes=int(data["resolution_minutes"]),
        )


@dataclass
class Survey:
    id: str
    ticket_id: str
    token: str
    sent_at: str
    rating: int | None = None
    remark: str = ""
    answered_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Survey:
        return cls(
            id=data["id"],
            ticket_id=data["ticket_id"],
            token=data["token"],
            sent_at=data["sent_at"],
            rating=data.get("rating"),
            remark=data.get("remark", ""),
            answered_at=data.get("answered_at"),
        )


@dataclass
class AuditEntry:
    seq: int
    at: str
    actor: str
    action: str
    target: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        return cls(
            seq=data["seq"],
            at=data["at"],
            actor=data["actor"],
            action=data["action"],
            target=data.get("target", ""),
            details=dict(data.get("details", {})),
        )


@dataclass
class OutgoingMail:
    id: int
    to: str
    subject: str
    body: str
    template: str
    ticket_id: str | None = None
    recipient_agent: str | None = None
    created_at: str = ""
    sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutgoingMail:
        return cls(
            id=data["id"],
            to=data["to"],
            subject=data["subject"],
            body=data["body"],
            template=data.get("template", ""),
            ticket_id=data.get("ticket_id"),
            recipient_agent=data.get("recipient_agent"),
            created_at=data.get("created_at", ""),
            sent=data.get("sent", False),
        )
