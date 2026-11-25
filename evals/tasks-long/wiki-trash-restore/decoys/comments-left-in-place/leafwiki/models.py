"""The wiki's records and how they map to and from JSON.

Each record has ``to_dict`` and ``from_dict``; those dictionaries are what the store
writes, what backups contain, and what ``--json`` output prints.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .textutil import slugify


@dataclass(frozen=True)
class Revision:
    number: int
    at: str
    author: str
    summary: str
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "at": self.at,
            "author": self.author,
            "summary": self.summary,
            "body": self.body,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Revision:
        return cls(
            number=int(data["number"]),
            at=data["at"],
            author=data.get("author", ""),
            summary=data.get("summary", ""),
            body=data.get("body", ""),
        )


@dataclass(frozen=True)
class Attachment:
    name: str
    blob: str
    size: int
    content_type: str
    added_at: str
    added_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "blob": self.blob,
            "size": self.size,
            "content_type": self.content_type,
            "added_at": self.added_at,
            "added_by": self.added_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attachment:
        return cls(
            name=data["name"],
            blob=data["blob"],
            size=int(data["size"]),
            content_type=data.get("content_type", "application/octet-stream"),
            added_at=data.get("added_at", ""),
            added_by=data.get("added_by", ""),
        )


@dataclass
class Page:
    id: str
    title: str
    created_at: str
    revisions: list[Revision] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    attachments: dict[str, Attachment] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def current(self) -> Revision:
        return self.revisions[-1]

    @property
    def body(self) -> str:
        return self.current.body

    @property
    def updated_at(self) -> str:
        return self.current.at

    @property
    def author(self) -> str:
        return self.revisions[0].author

    @property
    def last_author(self) -> str:
        return self.current.author

    def revision(self, number: int) -> Revision | None:
        for revision in self.revisions:
            if revision.number == number:
                return revision
        return None

    def next_revision_number(self) -> int:
        return self.revisions[-1].number + 1 if self.revisions else 1

    def copy(self) -> Page:
        return replace(
            self,
            revisions=list(self.revisions),
            tags=list(self.tags),
            attachments=dict(self.attachments),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "tags": list(self.tags),
            "revisions": [r.to_dict() for r in self.revisions],
            "attachments": [a.to_dict() for a in self.attachments.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Page:
        attachments = [Attachment.from_dict(a) for a in data.get("attachments", [])]
        return cls(
            id=data["id"],
            title=data["title"],
            created_at=data["created_at"],
            revisions=[Revision.from_dict(r) for r in data.get("revisions", [])],
            tags=list(data.get("tags", [])),
            attachments={a.name: a for a in sorted(attachments, key=lambda a: a.name)},
        )


@dataclass(frozen=True)
class Comment:
    id: str
    page_id: str
    author: str
    at: str
    text: str
    reply_to: str | None = None
    edited_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "page_id": self.page_id,
            "author": self.author,
            "at": self.at,
            "text": self.text,
        }
        if self.reply_to:
            data["reply_to"] = self.reply_to
        if self.edited_at:
            data["edited_at"] = self.edited_at
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Comment:
        return cls(
            id=data["id"],
            page_id=data["page_id"],
            author=data.get("author", ""),
            at=data["at"],
            text=data.get("text", ""),
            reply_to=data.get("reply_to"),
            edited_at=data.get("edited_at"),
        )


CHANGE_KINDS = (
    "create",
    "edit",
    "revert",
    "rename",
    "delete",
    "tag",
    "attach",
    "detach",
    "comment",
    "restore",
    "purge",
)


@dataclass(frozen=True)
class Change:
    """One line of the recent-changes log."""

    seq: int
    at: str
    kind: str
    page_id: str
    title: str
    author: str
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "kind": self.kind,
            "page_id": self.page_id,
            "title": self.title,
            "author": self.author,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Change:
        return cls(
            seq=int(data["seq"]),
            at=data["at"],
            kind=data["kind"],
            page_id=data.get("page_id", ""),
            title=data["title"],
            author=data.get("author", ""),
            summary=data.get("summary", ""),
        )


@dataclass(frozen=True)
class TrashEntry:
    """A page in the trash, as listed by ``Wiki.trash()``."""

    id: str
    title: str
    deleted_at: str
    deleted_by: str


def trash_record(
    entry_id: str,
    page: Page,
    comments: list[Comment],
    watchers: list[str],
    deleted_at: str,
    deleted_by: str,
) -> dict[str, Any]:
    """What the store keeps for a page in the trash: the entry plus everything of the page."""
    return {
        "id": entry_id,
        "title": page.title,
        "deleted_at": deleted_at,
        "deleted_by": deleted_by,
        "page": page.to_dict(),
        "comments": [c.to_dict() for c in comments],
        "watchers": sorted(watchers),
    }


def trash_entry(record: dict[str, Any]) -> TrashEntry:
    return TrashEntry(
        id=record["id"],
        title=record["title"],
        deleted_at=record["deleted_at"],
        deleted_by=record.get("deleted_by", ""),
    )


@dataclass(frozen=True)
class Message:
    """A notification waiting in the outbox for whatever delivers mail."""

    to: str
    event: str
    page: str
    by: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return {"to": self.to, "event": self.event, "page": self.page, "by": self.by, "at": self.at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            to=data["to"],
            event=data["event"],
            page=data["page"],
            by=data.get("by", ""),
            at=data["at"],
        )


@dataclass(frozen=True)
class SearchHit:
    title: str
    score: float
    snippet: str
