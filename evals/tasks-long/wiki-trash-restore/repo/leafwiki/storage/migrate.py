"""Upgrading wikis written by leafwiki 1.x.

Format 1 kept the whole wiki in ``wiki.json``::

    {"format": 1,
     "site_name": "...",
     "pages": [{"title": ..., "tags": [...], "deleted": false,
                "history": [{"at": ..., "author": ..., "summary": ..., "body": ...}]}],
     "comments": [{"page": <title>, "author": ..., "at": ..., "text": ...}]}

1.x had no real delete: deleting a page only set ``"deleted": true`` and hid it. Format 1
had no attachments, watchers or recent changes.
"""

from __future__ import annotations

from typing import Any

from ..errors import StoreError
from ..models import Comment, Page, Revision
from ..tags import normalise_tags
from ..textutil import clean_title, slugify
from .base import Store


def _page_from_v1(raw: dict[str, Any], page_id: str) -> Page:
    history = raw.get("history") or []
    if not history:
        raise StoreError(f"page {raw.get('title')!r} has no history")
    revisions = [
        Revision(
            number=n,
            at=entry["at"],
            author=entry.get("author", ""),
            summary=entry.get("summary", ""),
            body=entry.get("body", ""),
        )
        for n, entry in enumerate(history, start=1)
    ]
    return Page(
        id=page_id,
        title=clean_title(raw["title"]),
        created_at=revisions[0].at,
        revisions=revisions,
        tags=normalise_tags(raw.get("tags", [])),
    )


def upgrade_v1(store: Store, legacy: dict[str, Any], now: str) -> dict[str, int]:
    """Write a format 1 wiki into ``store`` in format 2. Returns what was carried over."""
    pages: list[Page] = []
    by_slug: dict[str, Page] = {}
    dropped = 0
    for raw in legacy.get("pages", []):
        if raw.get("deleted"):
            dropped += 1
            continue
        page = _page_from_v1(raw, f"p{len(pages) + 1}")
        if page.slug in by_slug:
            raise StoreError(f"two pages are called {page.title!r}")
        pages.append(page)
        by_slug[page.slug] = page

    comments: dict[str, list[Comment]] = {}
    count = 0
    for raw in legacy.get("comments", []):
        page = by_slug.get(slugify(raw.get("page", "")))
        if page is None:
            continue
        count += 1
        comments.setdefault(page.id, []).append(
            Comment(
                id=f"c{count}",
                page_id=page.id,
                author=raw.get("author", ""),
                at=raw["at"],
                text=raw.get("text", ""),
            )
        )

    for page in pages:
        store.write_page(page)
    for page_id, page_comments in comments.items():
        store.write_comments(page_id, page_comments)
    settings: dict[str, Any] = {}
    if legacy.get("site_name"):
        settings["site_name"] = legacy["site_name"]
    store.write_meta(
        {
            "settings": settings,
            "counters": {"page": len(pages), "comment": count, "change": 0},
            "generation": 1,
            "upgraded_at": now,
        }
    )
    return {"pages": len(pages), "comments": count, "dropped": dropped}
