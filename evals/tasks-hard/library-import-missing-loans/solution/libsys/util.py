"""Small helpers shared across libsys."""

import itertools
from collections.abc import Callable, Hashable, Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")
K = TypeVar("K", bound=Hashable)


def group_by(items: Iterable[T], key: Callable[[T], K]) -> dict[K, list[T]]:
    """Group items by key.

    Returns {key: [items with that key]}: keys in the order they first appear, and
    each group's items in their original order. The items don't need to be sorted.
    """
    groups: dict[K, list[T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Consecutive lists of at most `size` items."""
    if size < 1:
        raise ValueError("size must be at least 1")
    iterator = iter(items)
    while chunk := list(itertools.islice(iterator, size)):
        yield chunk


def unique(items: Iterable[T], key: Callable[[T], Hashable] | None = None) -> list[T]:
    """Items without repeats, keeping the first of each, in order."""
    seen: set[Hashable] = set()
    result: list[T] = []
    for item in items:
        marker = key(item) if key else item
        if marker not in seen:
            seen.add(marker)  # type: ignore[arg-type]
            result.append(item)
    return result


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
