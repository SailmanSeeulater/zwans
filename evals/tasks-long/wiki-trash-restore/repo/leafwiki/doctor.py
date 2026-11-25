"""``leafwiki check``: look for anything in the wiki's folder that doesn't add up.

A wiki that has only ever been changed through leafwiki has no problems to report;
anything listed here means a file was edited by hand, copied in half, or damaged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import StoreError
from .markup import plain_text
from .search.tokenize import term_counts

if TYPE_CHECKING:
    from .wiki import Wiki


def _check_pages(wiki: Wiki) -> list[str]:
    problems: list[str] = []
    seen_slugs: dict[str, str] = {}
    for page in wiki.pages():
        if page.slug in seen_slugs:
            problems.append(f"{page.title}: same address as {seen_slugs[page.slug]}")
        seen_slugs[page.slug] = page.title
        numbers = [r.number for r in page.revisions]
        if not numbers:
            problems.append(f"{page.title}: has no revisions")
        elif numbers != sorted(set(numbers)):
            problems.append(f"{page.title}: revisions are out of order")
        for attachment in page.attachments.values():
            if not wiki.store.has_blob(attachment.blob):
                problems.append(f"{page.title}: attachment {attachment.name} has no content")
            else:
                try:
                    size = len(wiki.store.read_blob(attachment.blob))
                except StoreError:
                    size = -1
                if size != attachment.size:
                    problems.append(f"{page.title}: attachment {attachment.name} has the wrong size")
    return problems


def _check_references(wiki: Wiki) -> list[str]:
    problems: list[str] = []
    live = {page.id for page in wiki.pages()}
    for page_id in wiki.store.comment_page_ids():
        if page_id not in live:
            problems.append(f"comments kept for a page that doesn't exist ({page_id})")
    for page_id in wiki.store.read_watchers():
        if page_id not in live:
            problems.append(f"watchers kept for a page that doesn't exist ({page_id})")
    return problems


def _check_index(wiki: Wiki) -> list[str]:
    pages = {page.id: page for page in wiki.pages()}
    indexed = set(wiki.index.docs)
    if indexed != set(pages):
        return ["the search index doesn't match the pages (run: leafwiki reindex)"]
    for page_id, page in pages.items():
        doc = wiki.index.docs[page_id]
        if doc.title != page.title or doc.tags != sorted(page.tags):
            return [f"the search index is out of date for {page.title} (run: leafwiki reindex)"]
        for term in term_counts(plain_text(page.body)):
            if page_id not in wiki.index.postings.get(term, {}):
                return [f"the search index is out of date for {page.title} (run: leafwiki reindex)"]
    return []


def _check_changes(wiki: Wiki) -> list[str]:
    seqs = [c.seq for c in wiki.store.read_changes()]
    if seqs != sorted(set(seqs)):
        return ["the recent-changes log is out of order"]
    return []


def check(wiki: Wiki) -> list[str]:
    """Every problem found, as sentences; an empty list means all is well."""
    return _check_pages(wiki) + _check_references(wiki) + _check_index(wiki) + _check_changes(wiki)
