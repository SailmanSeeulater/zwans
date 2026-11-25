"""Tags: how they are written, and the in-memory index of which pages carry which tag."""

from __future__ import annotations

import re
from collections.abc import Iterable

_ALLOWED = re.compile(r"[^\w\-.]+", re.UNICODE)
MAX_TAG = 40


def normalise_tag(tag: str) -> str:
    """Tags are lower case, without spaces or punctuation other than ``-`` ``_`` ``.``.

    >>> normalise_tag("  Kitchen Tips ")
    'kitchen-tips'
    >>> normalise_tag("#howto")
    'howto'
    """
    tag = tag.strip().lstrip("#").casefold()
    tag = re.sub(r"\s+", "-", tag)
    tag = _ALLOWED.sub("", tag).strip("-.")
    return tag[:MAX_TAG]


def normalise_tags(tags: Iterable[str]) -> list[str]:
    return sorted({t for t in (normalise_tag(tag) for tag in tags) if t})


class TagIndex:
    """Which page ids carry each tag. Kept up to date by the wiki as pages change."""

    def __init__(self) -> None:
        self._pages: dict[str, set[str]] = {}

    def add(self, page_id: str, tags: Iterable[str]) -> None:
        for tag in tags:
            self._pages.setdefault(tag, set()).add(page_id)

    def remove(self, page_id: str, tags: Iterable[str]) -> None:
        for tag in tags:
            ids = self._pages.get(tag)
            if ids is None:
                continue
            ids.discard(page_id)
            if not ids:
                del self._pages[tag]

    def replace(self, page_id: str, old: Iterable[str], new: Iterable[str]) -> None:
        self.remove(page_id, old)
        self.add(page_id, new)

    def pages(self, tag: str) -> set[str]:
        return set(self._pages.get(normalise_tag(tag), ()))

    def counts(self) -> dict[str, int]:
        return {tag: len(ids) for tag, ids in sorted(self._pages.items())}

    def clear(self) -> None:
        self._pages.clear()

    def __contains__(self, tag: str) -> bool:
        return normalise_tag(tag) in self._pages


def tag_cloud(counts: dict[str, int], steps: int = 5) -> dict[str, int]:
    """A size from 1 to ``steps`` per tag, for the export's tag page."""
    if not counts:
        return {}
    low, high = min(counts.values()), max(counts.values())
    if low == high:
        return {tag: 1 for tag in counts}
    return {
        tag: 1 + round((count - low) * (steps - 1) / (high - low)) for tag, count in counts.items()
    }
