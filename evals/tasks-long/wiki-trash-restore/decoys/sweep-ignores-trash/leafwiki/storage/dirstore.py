"""The directory store: a wiki is a folder of JSON files.

::

    wiki.json            the manifest: {"format": 2, settings, counters, generation}
    pages/<id>.json      one page with all its revisions and attachment records
    blobs/<ab>/<sha256>  attachment contents, by hash
    comments/<id>.json   the comments on one page
    watchers.json        page id -> people watching it
    changes.json         the recent-changes log
    outbox.json          notifications waiting to be sent
    index.json           the saved search index (rebuilt when missing or stale)
    trash/<entry>.json   a deleted page with its comments and watchers

Every file is replaced atomically (written next to its final name, then renamed), so a
crash never leaves half a file behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..errors import StoreError
from ..models import Change, Comment, Message, Page
from .base import FORMAT_VERSION, Store, blob_key

MANIFEST = "wiki.json"


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    write_atomic(path, text.encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise StoreError(f"{path} is damaged: {error}") from None


class DirStore(Store):
    def __init__(self, root: str | os.PathLike[str], create: bool = False) -> None:
        self.root = Path(root)
        self.legacy: dict[str, Any] | None = None
        manifest = self.root / MANIFEST
        if not manifest.exists():
            if not create:
                raise StoreError(f"{self.root} is not a leafwiki folder (no {MANIFEST})")
            self.root.mkdir(parents=True, exist_ok=True)
            write_json(manifest, {"format": FORMAT_VERSION})
        data = read_json(manifest, {})
        version = data.get("format")
        if version == 1:
            self.legacy = data
        elif version != FORMAT_VERSION:
            raise StoreError(
                f"{self.root} was written in format {version!r}; this leafwiki reads 1 and 2"
            )

    # -- paths ------------------------------------------------------------------------

    def _page_path(self, page_id: str) -> Path:
        return self.root / "pages" / f"{page_id}.json"

    def _blob_path(self, key: str) -> Path:
        return self.root / "blobs" / key[:2] / key

    def _comments_path(self, page_id: str) -> Path:
        return self.root / "comments" / f"{page_id}.json"

    @staticmethod
    def _ids_in(folder: Path) -> list[str]:
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.json") if not p.name.startswith("."))

    # -- manifest ---------------------------------------------------------------------

    def read_meta(self) -> dict[str, Any]:
        data = read_json(self.root / MANIFEST, {})
        data.pop("format", None)
        return data

    def write_meta(self, meta: dict[str, Any]) -> None:
        write_json(self.root / MANIFEST, {"format": FORMAT_VERSION, **meta})
        self.legacy = None

    # -- pages ------------------------------------------------------------------------

    def page_ids(self) -> list[str]:
        return self._ids_in(self.root / "pages")

    def read_page(self, page_id: str) -> Page | None:
        data = read_json(self._page_path(page_id))
        return Page.from_dict(data) if data is not None else None

    def write_page(self, page: Page) -> None:
        write_json(self._page_path(page.id), page.to_dict())

    def remove_page(self, page_id: str) -> None:
        self._page_path(page_id).unlink(missing_ok=True)

    # -- blobs ------------------------------------------------------------------------

    def blob_keys(self) -> list[str]:
        folder = self.root / "blobs"
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.glob("*/*") if not p.name.startswith("."))

    def read_blob(self, key: str) -> bytes:
        try:
            return self._blob_path(key).read_bytes()
        except FileNotFoundError:
            raise StoreError(f"attachment content {key[:12]}… is missing") from None

    def write_blob(self, data: bytes) -> str:
        key = blob_key(data)
        path = self._blob_path(key)
        if not path.exists():
            write_atomic(path, data)
        return key

    def remove_blob(self, key: str) -> None:
        path = self._blob_path(key)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def has_blob(self, key: str) -> bool:
        return self._blob_path(key).exists()

    # -- comments ---------------------------------------------------------------------

    def comment_page_ids(self) -> list[str]:
        return self._ids_in(self.root / "comments")

    def read_comments(self, page_id: str) -> list[Comment]:
        return [Comment.from_dict(c) for c in read_json(self._comments_path(page_id), [])]

    def write_comments(self, page_id: str, comments: list[Comment]) -> None:
        path = self._comments_path(page_id)
        if comments:
            write_json(path, [c.to_dict() for c in comments])
        else:
            path.unlink(missing_ok=True)

    # -- trash ------------------------------------------------------------------------

    def trash_ids(self) -> list[str]:
        return self._ids_in(self.root / "trash")

    def read_trash(self, entry_id: str) -> dict[str, Any] | None:
        return read_json(self.root / "trash" / f"{entry_id}.json")

    def write_trash(self, entry_id: str, record: dict[str, Any]) -> None:
        write_json(self.root / "trash" / f"{entry_id}.json", record)

    def remove_trash(self, entry_id: str) -> None:
        (self.root / "trash" / f"{entry_id}.json").unlink(missing_ok=True)

    # -- watchers, changes, outbox, index -----------------------------------------------

    def read_watchers(self) -> dict[str, list[str]]:
        return read_json(self.root / "watchers.json", {})

    def write_watchers(self, watchers: dict[str, list[str]]) -> None:
        write_json(self.root / "watchers.json", {k: sorted(v) for k, v in watchers.items() if v})

    def read_changes(self) -> list[Change]:
        return [Change.from_dict(c) for c in read_json(self.root / "changes.json", [])]

    def write_changes(self, changes: list[Change]) -> None:
        write_json(self.root / "changes.json", [c.to_dict() for c in changes])

    def read_outbox(self) -> list[Message]:
        return [Message.from_dict(m) for m in read_json(self.root / "outbox.json", [])]

    def write_outbox(self, messages: list[Message]) -> None:
        write_json(self.root / "outbox.json", [m.to_dict() for m in messages])

    def read_index(self) -> dict[str, Any] | None:
        return read_json(self.root / "index.json")

    def write_index(self, data: dict[str, Any]) -> None:
        write_atomic(
            self.root / "index.json",
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )

    def is_empty(self) -> bool:
        return not self.page_ids() and not self.trash_ids() and not self.read_meta()
