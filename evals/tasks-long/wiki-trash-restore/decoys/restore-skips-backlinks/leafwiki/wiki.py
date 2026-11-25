"""The wiki: every operation on pages goes through :class:`Wiki`.

The store only keeps records. The wiki keeps the derived views consistent with them: the
slug lookup, the tag index, the link graph and the search index (which is saved too, and
rebuilt from the pages whenever the saved copy is missing or out of date). It also writes
the recent-changes log and queues notifications for watchers.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from . import attachments as attachment_rules
from .changes import ChangeLog
from .clock import Clock, stamp, system_clock
from .comments import MAX_COMMENT, CommentBook, Thread
from .errors import (
    AttachmentNotFound,
    AttachmentTooLarge,
    PageExists,
    PageNotFound,
    RevisionNotFound,
    TrashEntryNotFound,
    WikiError,
)
from .links import LinkIndex
from .markup import extract_links, plain_text, render_html
from .models import (
    Attachment,
    Change,
    Comment,
    Message,
    Page,
    Revision,
    SearchHit,
    TrashEntry,
    trash_entry,
    trash_record,
)
from .revisions import auto_summary, diff
from .search import SearchIndex, parse_query
from .settings import Settings
from .storage import DirStore, MemoryStore, Store
from .storage.migrate import upgrade_v1
from .tags import TagIndex, normalise_tags
from .textutil import clean_title, excerpt, slugify, sort_key
from .watch import Outbox, Watchlist


@dataclass(frozen=True)
class Link:
    target: str
    slug: str
    exists: bool


class Wiki:
    def __init__(self, store: Store, clock: Clock | None = None) -> None:
        self.store = store
        self.clock = clock or system_clock
        meta = store.read_meta()
        if not meta.get("counters"):
            meta = {
                "settings": meta.get("settings", {}),
                "counters": {"page": 0, "comment": 0, "change": 0, "trash": 0},
                "generation": 0,
                "created_at": self._now(),
            }
            store.write_meta(meta)
        self._meta = meta
        self.settings = Settings(meta.get("settings"))
        self.comment_book = CommentBook(store)
        self.watchlist = Watchlist(store)
        self.outbox_queue = Outbox(store)
        self.changes = ChangeLog(store)
        self._pages: dict[str, Page] = {}
        self._slugs: dict[str, str] = {}
        self.tag_index = TagIndex()
        self.link_index = LinkIndex()
        for page_id in store.page_ids():
            page = store.read_page(page_id)
            if page is not None:
                self._remember(page)
        self.index = self._load_index()

    # -- opening ------------------------------------------------------------------------

    @classmethod
    def memory(cls, clock: Clock | None = None) -> Wiki:
        return cls(MemoryStore(), clock=clock)

    @classmethod
    def open(cls, path: str | os.PathLike[str], clock: Clock | None = None) -> Wiki:
        """Open the wiki in a folder, upgrading a 1.x wiki on the way."""
        store = DirStore(path)
        if store.legacy is not None:
            upgrade_v1(store, store.legacy, stamp((clock or system_clock)()))
        return cls(store, clock=clock)

    @classmethod
    def init(
        cls,
        path: str | os.PathLike[str],
        clock: Clock | None = None,
        **settings: Any,
    ) -> Wiki:
        """Create a new, empty wiki in a folder."""
        store = DirStore(path, create=True)
        if not store.is_empty():
            raise WikiError(f"{path} already holds a wiki")
        wiki = cls(store, clock=clock)
        for key, value in settings.items():
            if value is not None:
                wiki.set_setting(key, value)
        return wiki

    # -- internals ------------------------------------------------------------------------

    def _now(self) -> str:
        return stamp(self.clock())

    def _next(self, counter: str) -> int:
        counters = self._meta.setdefault("counters", {})
        counters[counter] = int(counters.get(counter, 0)) + 1
        self._save_meta()
        return counters[counter]

    def _save_meta(self) -> None:
        self._meta["settings"] = self.settings.to_dict()
        self.store.write_meta(self._meta)

    def _remember(self, page: Page) -> None:
        self._pages[page.id] = page
        self._slugs[page.slug] = page.id
        self.tag_index.add(page.id, page.tags)
        self.link_index.set_links(page.id, page.body)

    def _index_page(self, page: Page) -> None:
        self.index.add(page.id, page.title, plain_text(page.body), page.tags)

    def _load_index(self) -> SearchIndex:
        data = self.store.read_index()
        index = SearchIndex.from_dict(data) if data else None
        if index is None or index.generation != self._meta.get("generation", 0):
            index = self._build_index()
            self.store.write_index(index.to_dict())
        return index

    def _build_index(self) -> SearchIndex:
        index = SearchIndex()
        index.generation = self._meta.get("generation", 0)
        for page in self._pages.values():
            index.add(page.id, page.title, plain_text(page.body), page.tags)
        return index

    def _changed(self) -> None:
        """Pages changed: bump the generation and save the index alongside."""
        self._meta["generation"] = int(self._meta.get("generation", 0)) + 1
        self._save_meta()
        self.index.generation = self._meta["generation"]
        self.store.write_index(self.index.to_dict())

    def _store_page(self, page: Page) -> None:
        self.store.write_page(page)
        self._pages[page.id] = page

    def _live(self, title: str) -> Page:
        page_id = self._slugs.get(slugify(title))
        if page_id is None:
            raise PageNotFound(title)
        return self._pages[page_id]

    def _log(self, kind: str, page: Page, author: str, summary: str = "") -> Change:
        return self._log_title(kind, page.id, page.title, author, summary)

    def _log_title(
        self, kind: str, page_id: str, title: str, author: str, summary: str = ""
    ) -> Change:
        change = Change(
            seq=self._next("change"),
            at=self._now(),
            kind=kind,
            page_id=page_id,
            title=title,
            author=author,
            summary=summary,
        )
        return self.changes.record(change)

    def _notify(self, page: Page, event: str, author: str) -> list[Message]:
        return self.watchlist.notify(page.id, page.title, event, author, self._now())

    # -- settings -------------------------------------------------------------------------

    def set_setting(self, key: str, value: Any) -> None:
        self.settings.set(key, value)
        self._save_meta()

    def reset_setting(self, key: str) -> None:
        self.settings.reset(key)
        self._save_meta()

    # -- reading pages --------------------------------------------------------------------

    def exists(self, title: str) -> bool:
        return slugify(title) in self._slugs

    def page(self, title: str) -> Page:
        return self._live(title).copy()

    def page_by_id(self, page_id: str) -> Page:
        try:
            return self._pages[page_id].copy()
        except KeyError:
            raise PageNotFound(page_id) from None

    def pages(self) -> list[Page]:
        """Every page, by title."""
        return [p.copy() for p in sorted(self._pages.values(), key=lambda p: sort_key(p.title))]

    def titles(self) -> list[str]:
        return [p.title for p in self.pages()]

    def history(self, title: str) -> list[Revision]:
        return list(self._live(title).revisions)

    def revision(self, title: str, number: int) -> Revision:
        page = self._live(title)
        revision = page.revision(number)
        if revision is None:
            raise RevisionNotFound(page.title, number)
        return revision

    def diff(self, title: str, old: int, new: int) -> str:
        page = self._live(title)
        return diff(self.revision(title, old), self.revision(title, new), page.title)

    def render(self, title: str, href: Any = None) -> str:
        page = self._live(title)
        return render_html(page.body, href=href, exists=lambda slug: slug in self._slugs)

    # -- writing pages --------------------------------------------------------------------

    def create_page(
        self,
        title: str,
        body: str,
        author: str = "",
        summary: str = "",
        tags: Iterable[str] = (),
    ) -> Page:
        title = clean_title(title)
        if slugify(title) in self._slugs:
            raise PageExists(self._live(title).title)
        now = self._now()
        page = Page(
            id=f"p{self._next('page')}",
            title=title,
            created_at=now,
            revisions=[Revision(1, now, author, summary or "Created", body)],
            tags=normalise_tags(tags),
        )
        self.store.write_page(page)
        self._remember(page)
        self._index_page(page)
        self._log("create", page, author, summary)
        self._changed()
        return page.copy()

    def edit_page(self, title: str, body: str, author: str = "", summary: str = "") -> Page:
        page = self._live(title)
        if body == page.body:
            return page.copy()
        revision = Revision(
            page.next_revision_number(),
            self._now(),
            author,
            summary or auto_summary(page.body, body),
            body,
        )
        page = replace(page, revisions=[*page.revisions, revision])
        self._store_page(page)
        self.link_index.set_links(page.id, body)
        self._index_page(page)
        self._log("edit", page, author, revision.summary)
        self._notify(page, "edited", author)
        self._changed()
        return page.copy()

    def revert(self, title: str, number: int, author: str = "") -> Page:
        page = self._live(title)
        old = self.revision(title, number)
        if old.body == page.body:
            return page.copy()
        revision = Revision(
            page.next_revision_number(),
            self._now(),
            author,
            f"Reverted to revision {number}",
            old.body,
        )
        page = replace(page, revisions=[*page.revisions, revision])
        self._store_page(page)
        self.link_index.set_links(page.id, page.body)
        self._index_page(page)
        self._log("revert", page, author, revision.summary)
        self._notify(page, "edited", author)
        self._changed()
        return page.copy()

    def rename_page(self, title: str, new_title: str, author: str = "") -> Page:
        page = self._live(title)
        new_title = clean_title(new_title)
        if new_title == page.title:
            return page.copy()
        new_slug = slugify(new_title)
        if new_slug != page.slug and new_slug in self._slugs:
            raise PageExists(self._pages[self._slugs[new_slug]].title)
        old_title = page.title
        del self._slugs[page.slug]
        page = replace(page, title=new_title)
        self._store_page(page)
        self._slugs[page.slug] = page.id
        self.index.retitle(page.id, page.title)
        self._log("rename", page, author, f"{old_title} → {new_title}")
        self._notify(page, "renamed", author)
        self._changed()
        return page.copy()

    def delete_page(self, title: str, author: str = "") -> str:
        """Move a page to the trash. Returns the trash entry's id."""
        page = self._live(title)
        self._notify(page, "deleted", author)
        self._log("delete", page, author)
        entry_id = f"t{self._next('trash')}"
        comments = self.comment_book.for_page(page.id)
        watchers = self.watchlist.watchers(page.id)
        self.store.write_trash(
            entry_id,
            trash_record(entry_id, page, comments, watchers, self._now(), author),
        )
        self.store.remove_page(page.id)
        del self._pages[page.id]
        del self._slugs[page.slug]
        self.tag_index.remove(page.id, page.tags)
        self.link_index.drop(page.id)
        self.index.remove(page.id)
        self.comment_book.drop_page(page.id)
        self.watchlist.drop_page(page.id)
        self._changed()
        return entry_id

    # -- the trash ------------------------------------------------------------------------

    def _trash_record(self, entry_id: str) -> dict[str, Any]:
        record = self.store.read_trash(entry_id)
        if record is None:
            raise TrashEntryNotFound(entry_id)
        return record

    def trash(self) -> list[TrashEntry]:
        """Pages in the trash, most recently deleted first."""
        entries = [trash_entry(self.store.read_trash(eid)) for eid in self.store.trash_ids()]
        entries.sort(key=lambda e: (e.deleted_at, int(e.id.lstrip("t") or 0)), reverse=True)
        return entries

    def restore_page(self, entry_id: str, author: str = "", title: str | None = None) -> Page:
        """Bring a page back from the trash, exactly as it was deleted."""
        record = self._trash_record(entry_id)
        page = Page.from_dict(record["page"])
        if title is not None:
            page = replace(page, title=clean_title(title))
        if page.slug in self._slugs:
            raise PageExists(self._pages[self._slugs[page.slug]].title)
        comments = [Comment.from_dict(c) for c in record.get("comments", [])]
        watchers = list(record.get("watchers", []))
        self.store.write_page(page)
        self._pages[page.id] = page
        self._slugs[page.slug] = page.id
        self.tag_index.add(page.id, page.tags)
        self._index_page(page)
        if comments:
            self.comment_book.put_page(page.id, comments)
        if watchers:
            self.watchlist.set_watchers(page.id, watchers)
        self.store.remove_trash(entry_id)
        self._log("restore", page, author)
        self._notify(page, "restored", author)
        self._changed()
        return page.copy()

    def purge_page(self, entry_id: str, author: str = "") -> TrashEntry:
        """Delete a page in the trash for good."""
        record = self._trash_record(entry_id)
        entry = trash_entry(record)
        page = Page.from_dict(record["page"])
        self.store.remove_trash(entry_id)
        still_used = self.blobs_in_use()
        for attachment in page.attachments.values():
            if attachment.blob not in still_used:
                self.store.remove_blob(attachment.blob)
        self._log_title("purge", page.id, entry.title, author)
        self.watchlist.notify(
            page.id, entry.title, "purged", author, self._now(), users=record.get("watchers", [])
        )
        return entry

    def blobs_in_use(self) -> set[str]:
        """Attachment contents used by a live page or a page in the trash."""
        used = {a.blob for page in self._pages.values() for a in page.attachments.values()}
        for entry_id in self.store.trash_ids():
            record = self.store.read_trash(entry_id) or {}
            for attachment in record.get("page", {}).get("attachments", []):
                used.add(attachment["blob"])
        return used

    # -- tags -----------------------------------------------------------------------------

    def set_tags(self, title: str, tags: Iterable[str], author: str = "") -> Page:
        page = self._live(title)
        new = normalise_tags(tags)
        if new == page.tags:
            return page.copy()
        added = [f"+{t}" for t in new if t not in page.tags]
        removed = [f"-{t}" for t in page.tags if t not in new]
        self.tag_index.replace(page.id, page.tags, new)
        page = replace(page, tags=new)
        self._store_page(page)
        self._index_page(page)
        self._log("tag", page, author, " ".join(added + removed))
        self._changed()
        return page.copy()

    def add_tags(self, title: str, tags: Iterable[str], author: str = "") -> Page:
        page = self._live(title)
        return self.set_tags(title, [*page.tags, *tags], author)

    def remove_tags(self, title: str, tags: Iterable[str], author: str = "") -> Page:
        page = self._live(title)
        doomed = set(normalise_tags(tags))
        return self.set_tags(title, [t for t in page.tags if t not in doomed], author)

    def tags(self) -> dict[str, int]:
        """Every tag in use, with how many pages carry it."""
        return self.tag_index.counts()

    def pages_tagged(self, tag: str) -> list[str]:
        return sorted((self._pages[pid].title for pid in self.tag_index.pages(tag)), key=sort_key)

    # -- links ----------------------------------------------------------------------------

    def links(self, title: str) -> list[Link]:
        page = self._live(title)
        return [
            Link(link.target, link.slug, link.slug in self._slugs)
            for link in extract_links(page.body)
        ]

    def backlinks(self, title: str) -> list[str]:
        """Titles of the pages that link to ``title`` (which needn't exist)."""
        slug = slugify(title)
        own = self._slugs.get(slug)
        sources = self.link_index.incoming(slug) - {own}
        return sorted((self._pages[pid].title for pid in sources), key=sort_key)

    def wanted(self) -> dict[str, list[str]]:
        """Pages linked to but never written: slug -> titles of the pages linking there."""
        out: dict[str, list[str]] = {}
        for slug in sorted(self.link_index.linked_slugs()):
            if slug not in self._slugs:
                out[slug] = self.backlinks(slug)
        return out

    def orphans(self) -> list[str]:
        """Pages nothing else links to."""
        return [p.title for p in self.pages() if not self.backlinks(p.title)]

    # -- attachments ----------------------------------------------------------------------

    def attach(
        self,
        title: str,
        name: str,
        data: bytes,
        author: str = "",
        content_type: str | None = None,
    ) -> Attachment:
        page = self._live(title)
        name = attachment_rules.check_name(name)
        limit = self.settings.max_attachment_bytes
        if len(data) > limit:
            raise AttachmentTooLarge(f"{name} is {len(data)} bytes; the limit is {limit}")
        key = self.store.write_blob(data)
        attachment = Attachment(
            name=name,
            blob=key,
            size=len(data),
            content_type=content_type or attachment_rules.content_type(name),
            added_at=self._now(),
            added_by=author,
        )
        files = dict(page.attachments)
        files[name] = attachment
        page = replace(page, attachments=dict(sorted(files.items())))
        self._store_page(page)
        self._log("attach", page, author, name)
        self._notify(page, "attached", author)
        return attachment

    def detach(self, title: str, name: str, author: str = "") -> None:
        page = self._live(title)
        if name not in page.attachments:
            raise AttachmentNotFound(page.title, name)
        files = dict(page.attachments)
        del files[name]
        page = replace(page, attachments=files)
        self._store_page(page)
        self._log("detach", page, author, name)

    def attachments(self, title: str) -> list[Attachment]:
        return list(self._live(title).attachments.values())

    def attachment(self, title: str, name: str) -> bytes:
        page = self._live(title)
        found = page.attachments.get(name)
        if found is None:
            raise AttachmentNotFound(page.title, name)
        return self.store.read_blob(found.blob)

    # -- comments -------------------------------------------------------------------------

    def comment(
        self, title: str, text: str, author: str = "", reply_to: str | None = None
    ) -> Comment:
        page = self._live(title)
        text = text.strip()
        if not text:
            raise WikiError("a comment can't be empty")
        if len(text) > MAX_COMMENT:
            raise WikiError(f"a comment can be at most {MAX_COMMENT} characters")
        comment = Comment(
            id=f"c{self._next('comment')}",
            page_id=page.id,
            author=author,
            at=self._now(),
            text=text,
            reply_to=reply_to,
        )
        self.comment_book.add(comment)
        self._log("comment", page, author, excerpt(text, 60))
        self._notify(page, "commented", author)
        return comment

    def comments(self, title: str) -> list[Comment]:
        return self.comment_book.for_page(self._live(title).id)

    def comment_threads(self, title: str) -> list[Thread]:
        return self.comment_book.threads(self._live(title).id)

    def edit_comment(self, comment_id: str, text: str) -> Comment:
        return self.comment_book.edit(comment_id, text.strip(), self._now())

    def delete_comment(self, comment_id: str) -> int:
        return len(self.comment_book.remove(comment_id))

    def recent_comments(self, limit: int = 20) -> list[tuple[str, Comment]]:
        """(page title, comment), newest first, across the whole wiki."""
        return [(self._pages[c.page_id].title, c) for c in self.comment_book.recent(limit)]

    # -- watching -------------------------------------------------------------------------

    def watch(self, title: str, user: str) -> bool:
        return self.watchlist.watch(self._live(title).id, user)

    def unwatch(self, title: str, user: str) -> bool:
        return self.watchlist.unwatch(self._live(title).id, user)

    def watchers(self, title: str) -> list[str]:
        return self.watchlist.watchers(self._live(title).id)

    def watched_by(self, user: str) -> list[str]:
        ids = self.watchlist.pages_watched_by(user)
        return sorted((self._pages[pid].title for pid in ids), key=sort_key)

    def outbox(self) -> list[Message]:
        return self.outbox_queue.messages()

    def drain_outbox(self) -> list[Message]:
        return self.outbox_queue.drain()

    # -- recent changes, search, maintenance ------------------------------------------------

    def recent_changes(self, limit: int | None = 50, kinds: Iterable[str] | None = None) -> list[Change]:
        return self.changes.recent(limit, kinds)

    def page_changes(self, title: str, limit: int | None = 50) -> list[Change]:
        return self.changes.recent(limit, page_id=self._live(title).id)

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        parsed = parse_query(query)
        return [
            SearchHit(self.index.docs[doc_id].title, score, snippet)
            for doc_id, score, snippet in self.index.search(parsed, limit)
        ]

    def rebuild_index(self) -> int:
        """Throw the search index away and index every page again."""
        self.index = self._build_index()
        self.store.write_index(self.index.to_dict())
        return len(self.index)

    def maintain(self):
        from .maintenance import run_maintenance

        return run_maintenance(self)
