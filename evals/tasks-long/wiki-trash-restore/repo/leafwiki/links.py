"""The link graph between pages.

Links point at slugs, not at pages: ``[[Kettle]]`` keeps pointing at "kettle" whether or
not such a page exists yet. That's what makes wanted pages (linked, never written) and
backlinks to a page that is created later work without any bookkeeping.
"""

from __future__ import annotations

from collections.abc import Iterable

from .markup import extract_links


class LinkIndex:
    def __init__(self) -> None:
        self._outgoing: dict[str, list[str]] = {}
        self._incoming: dict[str, set[str]] = {}

    def set_links(self, page_id: str, body: str) -> None:
        """Record the links in a page's current text, replacing what it linked before."""
        self.drop(page_id)
        targets = [link.slug for link in extract_links(body)]
        self._outgoing[page_id] = targets
        for slug in targets:
            self._incoming.setdefault(slug, set()).add(page_id)

    def drop(self, page_id: str) -> None:
        for slug in self._outgoing.pop(page_id, []):
            sources = self._incoming.get(slug)
            if sources is not None:
                sources.discard(page_id)
                if not sources:
                    del self._incoming[slug]

    def outgoing(self, page_id: str) -> list[str]:
        return list(self._outgoing.get(page_id, []))

    def incoming(self, slug: str) -> set[str]:
        return set(self._incoming.get(slug, ()))

    def linked_slugs(self) -> set[str]:
        return set(self._incoming)

    def rebuild(self, pages: Iterable[tuple[str, str]]) -> None:
        """Start over from (page id, body) pairs."""
        self._outgoing.clear()
        self._incoming.clear()
        for page_id, body in pages:
            self.set_links(page_id, body)
