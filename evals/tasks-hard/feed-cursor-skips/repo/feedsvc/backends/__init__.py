from feedsvc.backends.base import Backend
from feedsvc.backends.memory import MemoryBackend
from feedsvc.backends.sqlite import SQLiteBackend


def make_backend(kind: str = "sqlite", path: str = "feed.db") -> Backend:
    if kind == "memory":
        return MemoryBackend()
    if kind == "sqlite":
        return SQLiteBackend(path)
    raise ValueError(f"unknown backend {kind!r}")


__all__ = ["Backend", "MemoryBackend", "SQLiteBackend", "make_backend"]
