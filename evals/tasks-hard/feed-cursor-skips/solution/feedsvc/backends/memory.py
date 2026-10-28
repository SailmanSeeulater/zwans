from collections.abc import Collection
from datetime import datetime

from feedsvc.cursor import Cursor
from feedsvc.models import Post


def feed_order(post: Post) -> tuple[datetime, int]:
    return (post.created_at, post.id)


class MemoryBackend:
    def __init__(self) -> None:
        self._posts: dict[int, Post] = {}
        self._last_id = 0
        self._follows: dict[str, set[str]] = {}
        self._mutes: dict[str, set[str]] = {}

    # --- posts ----------------------------------------------------------------------

    def add_post(self, author: str, created_at: datetime, body: str) -> Post:
        self._last_id += 1
        post = Post(self._last_id, author, created_at, body)
        self._posts[post.id] = post
        return post

    def get_post(self, post_id: int) -> Post | None:
        return self._posts.get(post_id)

    def delete_post(self, post_id: int) -> bool:
        return self._posts.pop(post_id, None) is not None

    def _by(self, authors: Collection[str]) -> list[Post]:
        wanted = set(authors)
        posts = [post for post in self._posts.values() if post.author in wanted]
        return sorted(posts, key=feed_order, reverse=True)

    def posts(
        self,
        authors: Collection[str],
        *,
        older_than: Cursor | None = None,
        newer_than: Cursor | None = None,
        limit: int,
    ) -> list[Post]:
        result = []
        for post in self._by(authors):
            if older_than is not None and not feed_order(post) < older_than.key:
                continue
            if newer_than is not None and not feed_order(post) > newer_than.key:
                continue
            result.append(post)
            if len(result) == limit:
                break
        return result

    def posts_at_offset(self, authors: Collection[str], offset: int, limit: int) -> list[Post]:
        return self._by(authors)[offset : offset + limit]

    def count_posts(self, authors: Collection[str]) -> int:
        return len(self._by(authors))

    # --- follows and mutes ----------------------------------------------------------

    def follow(self, follower: str, followee: str) -> None:
        self._follows.setdefault(follower, set()).add(followee)

    def unfollow(self, follower: str, followee: str) -> None:
        self._follows.get(follower, set()).discard(followee)

    def following(self, user: str) -> set[str]:
        return set(self._follows.get(user, set()))

    def mute(self, user: str, author: str) -> None:
        self._mutes.setdefault(user, set()).add(author)

    def unmute(self, user: str, author: str) -> None:
        self._mutes.get(user, set()).discard(author)

    def muted(self, user: str) -> set[str]:
        return set(self._mutes.get(user, set()))

    def close(self) -> None:
        pass
