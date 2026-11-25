"""Statistics about the whole wiki and about single pages (``leafwiki stats``)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .markup import extract_links, plain_text
from .revisions import authors
from .textutil import sort_key, word_count

if TYPE_CHECKING:
    from .wiki import Wiki

TOP = 5


def wiki_stats(wiki: Wiki) -> dict[str, Any]:
    pages = wiki.pages()
    live = {page.slug: page for page in pages}

    inbound: dict[str, set[str]] = {}
    wanted: dict[str, str] = {}
    for page in pages:
        for link in extract_links(page.body):
            if link.slug == page.slug:
                continue
            inbound.setdefault(link.slug, set()).add(page.id)
            if link.slug not in live:
                wanted.setdefault(link.slug, link.target)

    comments = 0
    for page_id in wiki.store.comment_page_ids():
        comments += len(wiki.store.read_comments(page_id))

    everyone: set[str] = set()
    for page in pages:
        everyone.update(authors(page.revisions))

    linked = [
        (page.title, len(inbound.get(page.slug, ())))
        for page in pages
        if inbound.get(page.slug)
    ]
    linked.sort(key=lambda item: (-item[1], sort_key(item[0])))

    return {
        "pages": len(pages),
        "revisions": sum(len(page.revisions) for page in pages),
        "words": sum(word_count(plain_text(page.body)) for page in pages),
        "attachments": sum(len(page.attachments) for page in pages),
        "attachment_bytes": sum(a.size for page in pages for a in page.attachments.values()),
        "comments": comments,
        "tags": len(wiki.tags()),
        "authors": len(everyone),
        "top_linked": [list(item) for item in linked[:TOP]],
        "orphans": [page.title for page in pages if not inbound.get(page.slug)],
        "wanted": sorted(wanted.values(), key=sort_key),
        "trashed": len(wiki.trash()),
    }


def page_stats(wiki: Wiki, title: str) -> dict[str, Any]:
    page = wiki.page(title)
    return {
        "title": page.title,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
        "revisions": len(page.revisions),
        "authors": authors(page.revisions),
        "words": word_count(plain_text(page.body)),
        "attachments": len(page.attachments),
        "comments": len(wiki.comments(page.title)),
        "backlinks": len(wiki.backlinks(page.title)),
        "watchers": len(wiki.watchers(page.title)),
        "tags": list(page.tags),
    }


def format_stats(stats: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in stats.items():
        label = key.replace("_", " ")
        if isinstance(value, list):
            if value and isinstance(value[0], list):
                shown = ", ".join(f"{t} ({n})" for t, n in value)
            else:
                shown = ", ".join(str(v) for v in value)
            lines.append(f"{label}: {shown or '-'}")
        else:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)
