"""Categories form a tree written with colons: "Food:Groceries" is under "Food"."""

from __future__ import annotations

from .errors import DuplicateName, NotFound, ValidationError

SEPARATOR = ":"


def clean(name: str) -> str:
    parts = [part.strip() for part in str(name).split(SEPARATOR)]
    if not all(parts):
        raise ValidationError(f"not a category name: {name!r}")
    return SEPARATOR.join(parts)


def parent_of(name: str) -> str | None:
    head, sep, _ = name.rpartition(SEPARATOR)
    return head if sep else None


def is_under(name: str | None, ancestor: str) -> bool:
    """True for the category itself and anything below it."""
    if name is None:
        return False
    return name == ancestor or name.startswith(ancestor + SEPARATOR)


def top_level(name: str) -> str:
    return name.split(SEPARATOR, 1)[0]


class CategoryTree:
    def __init__(self, names: list[str] | None = None) -> None:
        self._names: set[str] = set()
        for name in names or ():
            self.add(name)

    def add(self, name: str) -> str:
        name = clean(name)
        parts = name.split(SEPARATOR)
        for depth in range(1, len(parts) + 1):
            self._names.add(SEPARATOR.join(parts[:depth]))
        return name

    def ensure(self, name: str | None) -> str | None:
        return None if name is None else self.add(name)

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def names(self) -> list[str]:
        return sorted(self._names)

    def children(self, name: str) -> list[str]:
        prefix = name + SEPARATOR
        return sorted(
            other for other in self._names
            if other.startswith(prefix) and SEPARATOR not in other[len(prefix):]
        )

    def descendants(self, name: str) -> list[str]:
        return sorted(other for other in self._names if is_under(other, name))

    def rename(self, old: str, new: str) -> dict[str, str]:
        """Rename a category and everything under it; returns old->new for each name."""
        old, new = clean(old), clean(new)
        if old not in self._names:
            raise NotFound(f"no category {old!r}")
        if new in self._names:
            raise DuplicateName(f"category {new!r} already exists")
        mapping = {name: new + name[len(old):] for name in self.descendants(old)}
        for name in mapping:
            self._names.discard(name)
        for name in mapping.values():
            self.add(name)
        return mapping

    def remove(self, name: str) -> list[str]:
        name = clean(name)
        if name not in self._names:
            raise NotFound(f"no category {name!r}")
        gone = self.descendants(name)
        self._names.difference_update(gone)
        return gone
