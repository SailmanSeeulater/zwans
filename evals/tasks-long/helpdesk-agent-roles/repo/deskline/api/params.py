"""Reading and checking the ``params`` of an API request."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError

_MISSING = object()


class Params:
    def __init__(self, raw: Any) -> None:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValidationError("params must be an object")
        self.raw = raw
        self.used: set[str] = set()

    def _get(self, name: str, default: Any) -> Any:
        self.used.add(name)
        value = self.raw.get(name, _MISSING)
        if value is _MISSING:
            if default is _MISSING:
                raise ValidationError(f"missing parameter {name!r}")
            return default
        return value

    def str(self, name: str, default: Any = _MISSING) -> Any:
        value = self._get(name, default)
        if value is default and default is not _MISSING:
            return value
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be a string")
        return value

    def int(self, name: str, default: Any = _MISSING) -> Any:
        value = self._get(name, default)
        if value is default and default is not _MISSING:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{name} must be a whole number")
        return value

    def bool(self, name: str, default: Any = _MISSING) -> Any:
        value = self._get(name, default)
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be true or false")
        return value

    def list(self, name: str, default: Any = _MISSING) -> Any:
        value = self._get(name, default)
        if value is default and default is not _MISSING:
            return value
        if not isinstance(value, list):
            raise ValidationError(f"{name} must be a list")
        return value

    def dict(self, name: str, default: Any = _MISSING) -> Any:
        value = self._get(name, default)
        if value is default and default is not _MISSING:
            return value
        if not isinstance(value, dict):
            raise ValidationError(f"{name} must be an object")
        return value

    def any(self, name: str, default: Any = _MISSING) -> Any:
        return self._get(name, default)

    def finish(self) -> None:
        extra = set(self.raw) - self.used
        if extra:
            raise ValidationError(f"unknown parameter(s): {', '.join(sorted(extra))}")
