"""Comments on pages: storing them per page, finding one by id, threads, the latest ones."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .errors import CommentNotFound
from .models import Comment
from .storage import Store

MAX_COMMENT = 4000


@dataclass
class Thread:
    comment: Comment
    replies: list[Thread] = field(default_factory=list)


def _order(comment: Comment) -> tuple[str, int]:
    return (comment.at, int(comment.id.lstrip("c") or 0))


class CommentBook:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._where: dict[str, str] = {}
        for page_id in store.comment_page_ids():
            for comment in store.read_comments(page_id):
                self._where[comment.id] = page_id

    def for_page(self, page_id: str) -> list[Comment]:
        return sorted(self.store.read_comments(page_id), key=_order)

    def count(self, page_id: str) -> int:
        return len(self.store.read_comments(page_id))

    def get(self, comment_id: str) -> Comment:
        page_id = self._where.get(comment_id)
        if page_id is None:
            raise CommentNotFound(comment_id)
        for comment in self.store.read_comments(page_id):
            if comment.id == comment_id:
                return comment
        raise CommentNotFound(comment_id)

    def page_of(self, comment_id: str) -> str:
        try:
            return self._where[comment_id]
        except KeyError:
            raise CommentNotFound(comment_id) from None

    def add(self, comment: Comment) -> None:
        if comment.reply_to is not None and self._where.get(comment.reply_to) != comment.page_id:
            raise CommentNotFound(comment.reply_to)
        comments = self.store.read_comments(comment.page_id)
        comments.append(comment)
        self.store.write_comments(comment.page_id, comments)
        self._where[comment.id] = comment.page_id

    def edit(self, comment_id: str, text: str, at: str) -> Comment:
        page_id = self.page_of(comment_id)
        comments = self.store.read_comments(page_id)
        for i, comment in enumerate(comments):
            if comment.id == comment_id:
                comments[i] = replace(comment, text=text, edited_at=at)
                self.store.write_comments(page_id, comments)
                return comments[i]
        raise CommentNotFound(comment_id)

    def remove(self, comment_id: str) -> list[Comment]:
        """Delete a comment and every reply under it. Returns what was removed."""
        page_id = self.page_of(comment_id)
        comments = self.store.read_comments(page_id)
        doomed = {comment_id}
        grew = True
        while grew:
            grew = False
            for comment in comments:
                if comment.reply_to in doomed and comment.id not in doomed:
                    doomed.add(comment.id)
                    grew = True
        kept = [c for c in comments if c.id not in doomed]
        removed = [c for c in comments if c.id in doomed]
        self.store.write_comments(page_id, kept)
        for comment in removed:
            self._where.pop(comment.id, None)
        return removed

    def drop_page(self, page_id: str) -> list[Comment]:
        comments = self.store.read_comments(page_id)
        self.store.write_comments(page_id, [])
        for comment in comments:
            self._where.pop(comment.id, None)
        return comments

    def threads(self, page_id: str) -> list[Thread]:
        nodes = {c.id: Thread(c) for c in self.for_page(page_id)}
        roots: list[Thread] = []
        for node in nodes.values():
            parent = nodes.get(node.comment.reply_to or "")
            (parent.replies if parent else roots).append(node)
        return roots

    def recent(self, limit: int = 20) -> list[Comment]:
        everything: list[Comment] = []
        for page_id in self.store.comment_page_ids():
            everything.extend(self.store.read_comments(page_id))
        everything.sort(key=_order, reverse=True)
        return everything[:limit]
