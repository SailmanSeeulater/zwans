"""A store that lives in memory, for tests and throwaway wikis.

Records are kept as dictionaries, the same shape the directory store writes, so nothing
handed out can be changed behind the store's back.
"""

from __future__ import annotations

import copy
from typing import Any

from ..models import Change, Comment, Message, Page
from .base import Store, blob_key


class MemoryStore(Store):
    def __init__(self) -> None:
        self._meta: dict[str, Any] = {}
        self._pages: dict[str, dict[str, Any]] = {}
        self._blobs: dict[str, bytes] = {}
        self._comments: dict[str, list[dict[str, Any]]] = {}
        self._watchers: dict[str, list[str]] = {}
        self._changes: list[dict[str, Any]] = []
        self._outbox: list[dict[str, Any]] = []
        self._index: dict[str, Any] | None = None
        self._trash: dict[str, dict[str, Any]] = {}

    def read_meta(self) -> dict[str, Any]:
        return copy.deepcopy(self._meta)

    def write_meta(self, meta: dict[str, Any]) -> None:
        self._meta = copy.deepcopy(meta)

    def page_ids(self) -> list[str]:
        return list(self._pages)

    def read_page(self, page_id: str) -> Page | None:
        data = self._pages.get(page_id)
        return Page.from_dict(data) if data is not None else None

    def write_page(self, page: Page) -> None:
        self._pages[page.id] = page.to_dict()

    def remove_page(self, page_id: str) -> None:
        self._pages.pop(page_id, None)

    def blob_keys(self) -> list[str]:
        return list(self._blobs)

    def read_blob(self, key: str) -> bytes:
        return self._blobs[key]

    def write_blob(self, data: bytes) -> str:
        key = blob_key(data)
        self._blobs[key] = bytes(data)
        return key

    def remove_blob(self, key: str) -> None:
        self._blobs.pop(key, None)

    def has_blob(self, key: str) -> bool:
        return key in self._blobs

    def comment_page_ids(self) -> list[str]:
        return list(self._comments)

    def read_comments(self, page_id: str) -> list[Comment]:
        return [Comment.from_dict(c) for c in self._comments.get(page_id, [])]

    def write_comments(self, page_id: str, comments: list[Comment]) -> None:
        if comments:
            self._comments[page_id] = [c.to_dict() for c in comments]
        else:
            self._comments.pop(page_id, None)

    def read_watchers(self) -> dict[str, list[str]]:
        return copy.deepcopy(self._watchers)

    def write_watchers(self, watchers: dict[str, list[str]]) -> None:
        self._watchers = {k: sorted(v) for k, v in watchers.items() if v}

    def read_changes(self) -> list[Change]:
        return [Change.from_dict(c) for c in self._changes]

    def write_changes(self, changes: list[Change]) -> None:
        self._changes = [c.to_dict() for c in changes]

    def append_change(self, change: Change) -> None:
        self._changes.append(change.to_dict())

    def read_outbox(self) -> list[Message]:
        return [Message.from_dict(m) for m in self._outbox]

    def write_outbox(self, messages: list[Message]) -> None:
        self._outbox = [m.to_dict() for m in messages]

    def trash_ids(self) -> list[str]:
        return list(self._trash)

    def read_trash(self, entry_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._trash.get(entry_id))

    def write_trash(self, entry_id: str, record: dict[str, Any]) -> None:
        self._trash[entry_id] = copy.deepcopy(record)

    def remove_trash(self, entry_id: str) -> None:
        self._trash.pop(entry_id, None)

    def read_index(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._index)

    def write_index(self, data: dict[str, Any]) -> None:
        self._index = copy.deepcopy(data)
