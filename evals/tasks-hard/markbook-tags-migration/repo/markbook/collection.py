"""A collection of bookmarks: what a markbook file holds."""

from collections import Counter
from collections.abc import Iterator
from datetime import date
from typing import Any

from .model import Bookmark, DuplicateUrl, MarkbookError, NotFound, in_folder, normalize_folder
from .schema import CURRENT_VERSION
from .urls import is_web_url, normalize_url


class Collection:
    def __init__(self, bookmarks: list[Bookmark] | None = None, next_id: int = 1) -> None:
        self._bookmarks: dict[int, Bookmark] = {b.id: b for b in bookmarks or []}
        self.next_id = next_id
        self.loaded_version: int | None = None  # the format of the file it came from, if any

    # ----------------------------------------------------------- documents

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Collection":
        """From a valid, current document (see schema.validate)."""
        return cls([Bookmark.from_dict(b) for b in doc["bookmarks"]], doc["next_id"])

    def to_doc(self) -> dict[str, Any]:
        return {
            "version": CURRENT_VERSION,
            "next_id": self.next_id,
            "bookmarks": [b.to_dict() for b in self],
        }

    # --------------------------------------------------------------- reads

    def __iter__(self) -> Iterator[Bookmark]:
        return iter(sorted(self._bookmarks.values(), key=lambda b: b.id))

    def __len__(self) -> int:
        return len(self._bookmarks)

    def get(self, bookmark_id: int) -> Bookmark:
        try:
            return self._bookmarks[bookmark_id]
        except KeyError:
            raise NotFound(f"there is no bookmark {bookmark_id}") from None

    def by_url(self, url: str) -> Bookmark | None:
        wanted = normalize_url(url)
        for bookmark in self:
            if normalize_url(bookmark.url) == wanted:
                return bookmark
        return None

    def find(self, text: str) -> list[Bookmark]:
        """Bookmarks whose title, URL or folder contains text, ignoring case."""
        needle = text.lower()
        return [
            b
            for b in self
            if needle in b.title.lower() or needle in b.url.lower() or needle in b.folder.lower()
        ]

    def in_folder(self, folder: str) -> list[Bookmark]:
        """Bookmarks in folder or any folder inside it."""
        folder = normalize_folder(folder)
        return [b for b in self if in_folder(b.folder, folder)]

    def folders(self) -> dict[str, int]:
        """Each folder in use and how many bookmarks are directly in it, by name."""
        counts = Counter(b.folder for b in self if b.folder)
        return dict(sorted(counts.items()))

    def starred(self) -> list[Bookmark]:
        return [b for b in self if b.starred]

    # ------------------------------------------------------------- changes

    def add(
        self,
        url: str,
        title: str = "",
        folder: str = "",
        *,
        starred: bool = False,
        added: str | None = None,
    ) -> Bookmark:
        url = url.strip()
        if not is_web_url(url):
            raise MarkbookError(f"{url!r} is not an http(s) URL")
        if self.by_url(url) is not None:
            raise DuplicateUrl(f"{url} is already bookmarked")
        bookmark = Bookmark(
            id=self.next_id,
            url=url,
            title=title.strip() or url,
            folder=normalize_folder(folder),
            added=date.today().isoformat() if added is None else added,
            starred=starred,
        )
        self._bookmarks[bookmark.id] = bookmark
        self.next_id += 1
        return bookmark

    def remove(self, bookmark_id: int) -> Bookmark:
        bookmark = self.get(bookmark_id)
        del self._bookmarks[bookmark_id]
        return bookmark

    def move(self, bookmark_id: int, folder: str) -> Bookmark:
        bookmark = self.get(bookmark_id)
        bookmark.folder = normalize_folder(folder)
        return bookmark

    def star(self, bookmark_id: int, starred: bool = True) -> Bookmark:
        bookmark = self.get(bookmark_id)
        bookmark.starred = starred
        return bookmark

    def visit(self, bookmark_id: int) -> Bookmark:
        bookmark = self.get(bookmark_id)
        bookmark.visits += 1
        return bookmark
