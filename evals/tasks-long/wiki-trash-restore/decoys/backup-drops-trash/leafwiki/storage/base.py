"""The storage interface every backend implements, and the dump format backups use.

A store is deliberately dumb: it reads and writes records and knows nothing about what a
page means. The :class:`~leafwiki.wiki.Wiki` keeps everything consistent.
"""

from __future__ import annotations

import base64
import hashlib
from abc import ABC, abstractmethod
from typing import Any

from ..errors import StoreError
from ..models import Change, Comment, Message, Page

FORMAT_VERSION = 2


def blob_key(data: bytes) -> str:
    """Attachments are stored by content, so the same file attached twice is kept once."""
    return hashlib.sha256(data).hexdigest()


class Store(ABC):
    # -- the manifest: settings, counters, the index generation ----------------------

    @abstractmethod
    def read_meta(self) -> dict[str, Any]: ...

    @abstractmethod
    def write_meta(self, meta: dict[str, Any]) -> None: ...

    # -- pages, with their revisions and attachment records --------------------------

    @abstractmethod
    def page_ids(self) -> list[str]: ...

    @abstractmethod
    def read_page(self, page_id: str) -> Page | None: ...

    @abstractmethod
    def write_page(self, page: Page) -> None: ...

    @abstractmethod
    def remove_page(self, page_id: str) -> None: ...

    # -- attachment contents --------------------------------------------------------

    @abstractmethod
    def blob_keys(self) -> list[str]: ...

    @abstractmethod
    def read_blob(self, key: str) -> bytes: ...

    @abstractmethod
    def write_blob(self, data: bytes) -> str: ...

    @abstractmethod
    def remove_blob(self, key: str) -> None: ...

    def has_blob(self, key: str) -> bool:
        return key in self.blob_keys()

    # -- comments, per page -----------------------------------------------------------

    @abstractmethod
    def comment_page_ids(self) -> list[str]: ...

    @abstractmethod
    def read_comments(self, page_id: str) -> list[Comment]: ...

    @abstractmethod
    def write_comments(self, page_id: str, comments: list[Comment]) -> None:
        """Replace a page's comments; an empty list removes them."""

    # -- watchers: page id -> user names ------------------------------------------------

    @abstractmethod
    def read_watchers(self) -> dict[str, list[str]]: ...

    @abstractmethod
    def write_watchers(self, watchers: dict[str, list[str]]) -> None: ...

    # -- recent changes and the outbox --------------------------------------------------

    @abstractmethod
    def read_changes(self) -> list[Change]: ...

    @abstractmethod
    def write_changes(self, changes: list[Change]) -> None: ...

    def append_change(self, change: Change) -> None:
        self.write_changes([*self.read_changes(), change])

    @abstractmethod
    def read_outbox(self) -> list[Message]: ...

    @abstractmethod
    def write_outbox(self, messages: list[Message]) -> None: ...

    def append_messages(self, messages: list[Message]) -> None:
        if messages:
            self.write_outbox([*self.read_outbox(), *messages])

    # -- the trash: one record per deleted page, with everything that belonged to it ------

    @abstractmethod
    def trash_ids(self) -> list[str]: ...

    @abstractmethod
    def read_trash(self, entry_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def write_trash(self, entry_id: str, record: dict[str, Any]) -> None: ...

    @abstractmethod
    def remove_trash(self, entry_id: str) -> None: ...

    # -- the saved search index ---------------------------------------------------------

    @abstractmethod
    def read_index(self) -> dict[str, Any] | None: ...

    @abstractmethod
    def write_index(self, data: dict[str, Any]) -> None: ...

    # -- whole-wiki dumps, for backups ---------------------------------------------------

    def is_empty(self) -> bool:
        return not self.page_ids() and not self.trash_ids() and not self.read_meta()

    def dump(self) -> dict[str, Any]:
        """Everything in the store as one JSON-ready dictionary (the index excepted)."""
        return {
            "format": FORMAT_VERSION,
            "meta": self.read_meta(),
            "pages": [self.read_page(pid).to_dict() for pid in sorted(self.page_ids())],
            "blobs": {
                key: base64.b64encode(self.read_blob(key)).decode("ascii")
                for key in sorted(self.blob_keys())
            },
            "comments": {
                pid: [c.to_dict() for c in self.read_comments(pid)]
                for pid in sorted(self.comment_page_ids())
            },
            "watchers": self.read_watchers(),
            "changes": [c.to_dict() for c in self.read_changes()],
            "outbox": [m.to_dict() for m in self.read_outbox()],
        }

    def load_dump(self, data: dict[str, Any]) -> None:
        """Fill an empty store from :meth:`dump` output."""
        if data.get("format") != FORMAT_VERSION:
            raise StoreError(f"can't load a dump in format {data.get('format')!r}")
        if not self.is_empty():
            raise StoreError("a dump can only be loaded into an empty wiki")
        for key, encoded in data.get("blobs", {}).items():
            content = base64.b64decode(encoded)
            if blob_key(content) != key:
                raise StoreError(f"attachment {key[:12]}… is damaged")
            self.write_blob(content)
        for page in data.get("pages", []):
            self.write_page(Page.from_dict(page))
        for page_id, comments in data.get("comments", {}).items():
            self.write_comments(page_id, [Comment.from_dict(c) for c in comments])
        self.write_watchers({k: list(v) for k, v in data.get("watchers", {}).items()})
        self.write_changes([Change.from_dict(c) for c in data.get("changes", [])])
        self.write_outbox([Message.from_dict(m) for m in data.get("outbox", [])])
        meta = dict(data.get("meta", {}))
        meta["generation"] = int(meta.get("generation", 0)) + 1  # forces an index rebuild
        self.write_meta(meta)
