"""Publishing, following, and reading feeds."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from feedsvc import cursor as cursors
from feedsvc.backends.base import Backend
from feedsvc.cursor import Cursor
from feedsvc.models import Post, ValidationError, check_body, check_username, utc_seconds

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass
class FeedPage:
    items: list[Post]
    next: str | None = None  # cursor for the page after this one
    top: str | None = None  # cursor for /feed/refresh; only on first pages and refreshes
    gap: bool = False  # refresh only: more new posts than fit, reload the feed instead

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"items": [post.to_dict() for post in self.items]}
        if self.next is not None:
            data["next"] = self.next
        if self.top is not None:
            data["top"] = self.top
        if self.gap:
            data["gap"] = True
        return data


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        raise ValidationError("limit must be at least 1")
    return min(limit, MAX_LIMIT)


class FeedService:
    def __init__(self, backend: Backend, clock: Callable[[], datetime] | None = None) -> None:
        self.backend = backend
        self.clock = clock or (lambda: datetime.now(UTC))

    # --- writing --------------------------------------------------------------------

    def publish(self, author: str, body: str, *, at: datetime | None = None) -> Post:
        moment = utc_seconds(at if at is not None else self.clock())
        return self.backend.add_post(check_username(author), moment, check_body(body))

    def delete(self, author: str, post_id: int) -> None:
        post = self.backend.get_post(post_id)
        if post is None or post.author != check_username(author):
            raise LookupError(f"{author} has no post {post_id}")
        self.backend.delete_post(post_id)

    def follow(self, user: str, other: str) -> None:
        user, other = check_username(user), check_username(other)
        if user == other:
            raise ValidationError("you can't follow yourself")
        self.backend.follow(user, other)

    def unfollow(self, user: str, other: str) -> None:
        self.backend.unfollow(check_username(user), check_username(other))

    def mute(self, user: str, other: str) -> None:
        self.backend.mute(check_username(user), check_username(other))

    def unmute(self, user: str, other: str) -> None:
        self.backend.unmute(check_username(user), check_username(other))

    # --- reading --------------------------------------------------------------------

    def home_authors(self, user: str) -> set[str]:
        user = check_username(user)
        return (self.backend.following(user) | {user}) - self.backend.muted(user)

    def home(self, user: str, cursor: str | None = None, limit: int | None = None) -> FeedPage:
        return self._page(self.home_authors(user), cursor, clamp_limit(limit))

    def profile(self, author: str, cursor: str | None = None, limit: int | None = None) -> FeedPage:
        return self._page({check_username(author)}, cursor, clamp_limit(limit))

    def refresh(self, user: str, since: str) -> FeedPage:
        """Posts that arrived at the top of the home feed since `since` was handed out."""
        top = cursors.decode(since)
        newer = self.backend.posts(self.home_authors(user), newer_than=top, limit=MAX_LIMIT + 1)
        gap = len(newer) > MAX_LIMIT
        items = newer[:MAX_LIMIT]
        new_top = cursors.encode(Cursor.at(items[0])) if items else since
        return FeedPage(items, top=new_top, gap=gap)

    def home_by_page(self, user: str, page: int, limit: int | None = None) -> FeedPage:
        """Deprecated offset paging, still used by old app versions."""
        size = clamp_limit(limit)
        if page < 1:
            raise ValidationError("page must be at least 1")
        authors = self.home_authors(user)
        items = self.backend.posts_at_offset(authors, (page - 1) * size, size)
        more = self.backend.count_posts(authors) > page * size
        return FeedPage(items, next=str(page + 1) if more else None)

    def _page(self, authors: Collection[str], token: str | None, limit: int) -> FeedPage:
        after = cursors.decode(token) if token else None
        rows = self.backend.posts(authors, older_than=after, limit=limit + 1)
        items = rows[:limit]
        next_token = cursors.encode(Cursor.at(items[-1])) if len(rows) > limit else None
        top = None
        if token is None:
            top = cursors.encode(Cursor.at(items[0])) if items else cursors.encode(Cursor(EPOCH))
        return FeedPage(items, next=next_token, top=top)


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
