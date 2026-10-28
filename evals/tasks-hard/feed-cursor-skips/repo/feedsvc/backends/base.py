from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from feedsvc.cursor import Cursor
from feedsvc.models import Post


class Backend(Protocol):
    """Where posts, follows and mutes are kept.

    `posts()` returns posts in feed order: newest first, and among posts with the same
    timestamp, highest id first. `older_than` keeps only the posts after the cursor's
    position in that order; `newer_than` only the posts before it.
    """

    def add_post(self, author: str, created_at: datetime, body: str) -> Post: ...

    def get_post(self, post_id: int) -> Post | None: ...

    def delete_post(self, post_id: int) -> bool: ...

    def posts(
        self,
        authors: Collection[str],
        *,
        older_than: Cursor | None = None,
        newer_than: Cursor | None = None,
        limit: int,
    ) -> list[Post]: ...

    def posts_at_offset(self, authors: Collection[str], offset: int, limit: int) -> list[Post]: ...

    def count_posts(self, authors: Collection[str]) -> int: ...

    def follow(self, follower: str, followee: str) -> None: ...

    def unfollow(self, follower: str, followee: str) -> None: ...

    def following(self, user: str) -> set[str]: ...

    def mute(self, user: str, author: str) -> None: ...

    def unmute(self, user: str, author: str) -> None: ...

    def muted(self, user: str) -> set[str]: ...

    def close(self) -> None: ...
