import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime

from feedsvc.cursor import Cursor
from feedsvc.models import Post

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT NOT NULL,
    created_at INTEGER NOT NULL,  -- seconds since the epoch, UTC
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_by_author_time ON posts (author, created_at);
CREATE TABLE IF NOT EXISTS follows (
    follower TEXT NOT NULL,
    followee TEXT NOT NULL,
    PRIMARY KEY (follower, followee)
);
CREATE TABLE IF NOT EXISTS mutes (
    user TEXT NOT NULL,
    author TEXT NOT NULL,
    PRIMARY KEY (user, author)
);
"""


def _seconds(moment: datetime) -> int:
    return int(moment.timestamp())


def _row_to_post(row: sqlite3.Row) -> Post:
    return Post(
        row["id"], row["author"], datetime.fromtimestamp(row["created_at"], UTC), row["body"]
    )


class SQLiteBackend:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- posts ----------------------------------------------------------------------

    def add_post(self, author: str, created_at: datetime, body: str) -> Post:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO posts (author, created_at, body) VALUES (?, ?, ?)",
                (author, _seconds(created_at), body),
            )
        post = self.get_post(int(cursor.lastrowid or 0))
        assert post is not None
        return post

    def get_post(self, post_id: int) -> Post | None:
        row = self.db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return _row_to_post(row) if row else None

    def delete_post(self, post_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM posts WHERE id = ?", (post_id,)).rowcount > 0

    @staticmethod
    def _authors_clause(authors: Collection[str]) -> tuple[str, list[object]]:
        names = sorted(set(authors))
        if not names:
            return "0", []
        return f"author IN ({', '.join('?' for _ in names)})", list(names)

    def posts(
        self,
        authors: Collection[str],
        *,
        older_than: Cursor | None = None,
        newer_than: Cursor | None = None,
        limit: int,
    ) -> list[Post]:
        where, params = self._authors_clause(authors)
        conditions = [where]
        # Feed order is (created_at, id), newest first; a cursor is a position in it.
        if older_than is not None:
            conditions.append("(created_at < ? OR (created_at = ? AND id < ?))")
            seconds = _seconds(older_than.created_at)
            params += [seconds, seconds, older_than.post_id]
        if newer_than is not None:
            conditions.append("(created_at > ? OR (created_at = ? AND id > ?))")
            seconds = _seconds(newer_than.created_at)
            params += [seconds, seconds, newer_than.post_id]
        sql = (
            f"SELECT * FROM posts WHERE {' AND '.join(conditions)} "
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        params.append(limit)
        return [_row_to_post(row) for row in self.db.execute(sql, params)]

    def posts_at_offset(self, authors: Collection[str], offset: int, limit: int) -> list[Post]:
        where, params = self._authors_clause(authors)
        sql = (
            f"SELECT * FROM posts WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        )
        return [_row_to_post(row) for row in self.db.execute(sql, [*params, limit, offset])]

    def count_posts(self, authors: Collection[str]) -> int:
        where, params = self._authors_clause(authors)
        return int(
            self.db.execute(f"SELECT COUNT(*) FROM posts WHERE {where}", params).fetchone()[0]
        )

    # --- follows and mutes ----------------------------------------------------------

    def follow(self, follower: str, followee: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO follows VALUES (?, ?)", (follower, followee))

    def unfollow(self, follower: str, followee: str) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM follows WHERE follower = ? AND followee = ?", (follower, followee)
            )

    def following(self, user: str) -> set[str]:
        rows = self.db.execute("SELECT followee FROM follows WHERE follower = ?", (user,))
        return {row[0] for row in rows}

    def mute(self, user: str, author: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO mutes VALUES (?, ?)", (user, author))

    def unmute(self, user: str, author: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM mutes WHERE user = ? AND author = ?", (user, author))

    def muted(self, user: str) -> set[str]:
        return {
            row[0] for row in self.db.execute("SELECT author FROM mutes WHERE user = ?", (user,))
        }

    def close(self) -> None:
        self.db.close()
