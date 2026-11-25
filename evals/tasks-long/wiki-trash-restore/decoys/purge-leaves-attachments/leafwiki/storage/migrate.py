"""Upgrading wikis written by leafwiki 1.x.

Format 1 kept the whole wiki in ``wiki.json``::

    {"format": 1,
     "site_name": "...",
     "pages": [{"title": ..., "tags": [...], "deleted": false,
                "history": [{"at": ..., "author": ..., "summary": ..., "body": ...}]}],
     "comments": [{"page": <title>, "author": ..., "at": ..., "text": ...}]}

1.x had no real delete: deleting a page only set ``"deleted": true`` and hid it. Format 1
had no attachments, watchers or recent changes. Upgrading puts the flagged pages in the
trash, with their comments.
"""

from __future__ import annotations

from typing import Any

from ..errors import StoreError
from ..models import Comment, Page, Revision, trash_record
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
    trashed: list[Page] = []
    by_slug: dict[str, Page] = {}
    deleted_by_slug: dict[str, Page] = {}
    for raw in legacy.get("pages", []):
        page = _page_from_v1(raw, f"p{len(pages) + len(trashed) + 1}")
        if raw.get("deleted"):
            trashed.append(page)
            deleted_by_slug.setdefault(page.slug, page)
            continue
        if page.slug in by_slug:
            raise StoreError(f"two pages are called {page.title!r}")
        pages.append(page)
        by_slug[page.slug] = page

    comments: dict[str, list[Comment]] = {}
    count = 0
    for raw in legacy.get("comments", []):
        slug = slugify(raw.get("page", ""))
        page = by_slug.get(slug) or deleted_by_slug.get(slug)
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
        if page.id in comments:
            store.write_comments(page.id, comments[page.id])
    for number, page in enumerate(trashed, start=1):
        entry_id = f"t{number}"
        record = trash_record(entry_id, page, comments.get(page.id, []), [], now, "upgrade")
        store.write_trash(entry_id, record)
    settings: dict[str, Any] = {}
    if legacy.get("site_name"):
        settings["site_name"] = legacy["site_name"]
    store.write_meta(
        {
            "settings": settings,
            "counters": {
                "page": len(pages) + len(trashed),
                "comment": count,
                "change": 0,
                "trash": len(trashed),
            },
            "generation": 1,
            "upgraded_at": now,
        }
    )
    return {"pages": len(pages), "comments": count, "trashed": len(trashed)}
