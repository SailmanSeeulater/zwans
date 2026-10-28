"""Opaque paging cursors.

A cursor marks a position in a feed: "after this post" for the next page, or "the top
as of this post" for refresh. Clients get them as base64 strings and must not look inside.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from feedsvc.models import Post

VERSION = 2


class CursorError(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:
    # Posts can share a timestamp, so a position in the feed is the timestamp *and* the
    # id, the same two keys the feed is ordered by.
    created_at: datetime
    post_id: int = 0

    @classmethod
    def at(cls, post: Post) -> "Cursor":
        """The position of `post` in a feed."""
        return cls(post.created_at, post.id)

    @property
    def key(self) -> tuple[datetime, int]:
        return (self.created_at, self.post_id)


def encode(cursor: Cursor) -> str:
    payload = {"v": VERSION, "t": int(cursor.created_at.timestamp()), "id": cursor.post_id}
    raw = json.dumps(payload, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode(token: str) -> Cursor:
    padded = token + "=" * (-len(token) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise CursorError("not a valid cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") not in (1, VERSION):
        raise CursorError("not a valid cursor")
    seconds = payload.get("t")
    post_id = payload.get("id", 0)  # version 1 cursors had no id
    for value in (seconds, post_id):
        if not isinstance(value, int) or isinstance(value, bool):
            raise CursorError("not a valid cursor")
    return Cursor(datetime.fromtimestamp(seconds, UTC), post_id)
