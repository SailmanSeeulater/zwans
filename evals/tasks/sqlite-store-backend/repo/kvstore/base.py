"""The interface every backend implements.

Backends only implement the underscored methods. The public methods here check their
arguments first, so a backend can assume keys are non-empty strings and values are strings.
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class KeyNotFound(KeyError):
    pass


class Store(ABC):
    def get(self, key: str) -> str:
        """The value stored under key. Raises KeyNotFound if there is none."""
        return self._get(_check_key(key))

    def set(self, key: str, value: str) -> None:
        """Store value under key, replacing any value already there."""
        if not isinstance(value, str):
            raise TypeError(f"values must be strings, not {type(value).__name__}")
        self._set(_check_key(key), value)

    def delete(self, key: str) -> None:
        """Remove key. Raises KeyNotFound if there is none."""
        self._delete(_check_key(key))

    def keys(self, prefix: str = "") -> list[str]:
        """All keys that start with prefix, sorted.

        Keys are case-sensitive and the prefix is matched literally: no character in it has a
        special meaning.
        """
        return sorted(self._keys(prefix))

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str) or not key:
            return False
        try:
            self._get(key)
        except KeyNotFound:
            return False
        return True

    def close(self) -> None:  # noqa: B027 - most backends have nothing to release
        """Release whatever the backend holds open. The store must not be used afterwards."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @abstractmethod
    def _get(self, key: str) -> str: ...

    @abstractmethod
    def _set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def _delete(self, key: str) -> None: ...

    @abstractmethod
    def _keys(self, prefix: str) -> list[str]:
        """The keys starting with prefix, in any order."""


def _check_key(key: str) -> str:
    if not isinstance(key, str) or not key:
        raise ValueError("keys must be non-empty strings")
    return key
