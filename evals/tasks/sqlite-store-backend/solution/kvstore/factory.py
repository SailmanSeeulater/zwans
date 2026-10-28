"""Open a store from a URL like "json://data.json". See the README for the format."""

from collections.abc import Callable

from kvstore.base import Store
from kvstore.jsonfile import JsonFileStore
from kvstore.memory import MemoryStore
from kvstore.sqlite import SqliteStore


class UnknownBackend(ValueError):
    pass


# scheme -> a function that takes the location and opens the store
BACKENDS: dict[str, Callable[[str], Store]] = {
    "memory": lambda location: MemoryStore(),
    "json": JsonFileStore,
    "sqlite": SqliteStore,
}


def open_store(url: str) -> Store:
    scheme, separator, location = url.partition("://")
    if not separator:
        raise ValueError(f"not a store URL: {url!r}")
    try:
        backend = BACKENDS[scheme]
    except KeyError:
        known = ", ".join(sorted(BACKENDS))
        raise UnknownBackend(f"no backend called {scheme!r} (known: {known})") from None
    return backend(location)
