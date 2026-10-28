import sqlite3

from kvstore.base import KeyNotFound, Store


class SqliteStore(Store):
    """Keeps everything in one table of a SQLite database."""

    def __init__(self, path: str) -> None:
        self._connection = sqlite3.connect(path)
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _get(self, key: str) -> str:
        row = self._connection.execute(
            "SELECT value FROM entries WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise KeyNotFound(key)
        return row[0]

    def _set(self, key: str, value: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO entries (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def _delete(self, key: str) -> None:
        with self._connection:
            cursor = self._connection.execute("DELETE FROM entries WHERE key = ?", (key,))
        if cursor.rowcount == 0:
            raise KeyNotFound(key)

    def _keys(self, prefix: str) -> list[str]:
        # substr() compares exactly, where LIKE would treat % and _ as wildcards and ignore case.
        rows = self._connection.execute(
            "SELECT key FROM entries WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
        )
        return [row[0] for row in rows]

    def close(self) -> None:
        self._connection.close()
