"""Per-wiki settings, kept in the ``settings`` table of ``wiki.json``.

Every setting is declared once in :data:`SCHEMA` with its type, default and a check.
Unknown keys are refused, both when a file is read and when ``config`` sets one, so a typo
can't silently do nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import InvalidSetting


@dataclass(frozen=True)
class Option:
    name: str
    kind: type
    default: Any
    help: str
    check: Callable[[Any], str | None] | None = None


def _at_least(minimum: int) -> Callable[[Any], str | None]:
    def check(value: Any) -> str | None:
        return None if value >= minimum else f"must be at least {minimum}"

    return check


def _url(value: Any) -> str | None:
    if value and not value.startswith(("http://", "https://")):
        return "must start with http:// or https://"
    return None


SCHEMA: dict[str, Option] = {
    option.name: option
    for option in (
        Option("site_name", str, "My Wiki", "shown in page titles, feeds and the export"),
        Option("base_url", str, "http://localhost/wiki", "where the exported site lives", _url),
        Option("front_page", str, "Front Page", "the page the export's index links first"),
        Option(
            "keep_revisions",
            int,
            0,
            "revisions to keep per page when maintenance runs (0 keeps all)",
            _at_least(0),
        ),
        Option(
            "changes_retention_days",
            int,
            90,
            "days of recent changes maintenance keeps",
            _at_least(1),
        ),
        Option(
            "outbox_limit",
            int,
            1000,
            "messages the outbox holds before maintenance drops the oldest",
            _at_least(1),
        ),
        Option(
            "max_attachment_bytes",
            int,
            5_000_000,
            "largest attachment accepted",
            _at_least(1),
        ),
        Option("feed_items", int, 30, "items in the recent-changes feed", _at_least(1)),
        Option(
            "trash_retention_days",
            int,
            30,
            "days a deleted page stays in the trash before maintenance purges it",
            _at_least(1),
        ),
    )
}


def _coerce(option: Option, value: Any) -> Any:
    if option.kind is int:
        if isinstance(value, bool):
            raise InvalidSetting(f"{option.name} must be a whole number")
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                raise InvalidSetting(f"{option.name} must be a whole number") from None
        if not isinstance(value, int):
            raise InvalidSetting(f"{option.name} must be a whole number")
    elif option.kind is str:
        if not isinstance(value, str):
            raise InvalidSetting(f"{option.name} must be text")
        value = value.strip()
    if option.check:
        problem = option.check(value)
        if problem:
            raise InvalidSetting(f"{option.name} {problem}")
    return value


class Settings:
    """The settings of one wiki. Reads fall back to the schema's defaults."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = {}
        for key, value in (values or {}).items():
            self.set(key, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            option = SCHEMA[name]
        except KeyError:
            raise AttributeError(name) from None
        return self._values.get(name, option.default)

    def get(self, key: str) -> Any:
        if key not in SCHEMA:
            raise InvalidSetting(f"unknown setting {key!r}")
        return getattr(self, key)

    def set(self, key: str, value: Any) -> None:
        option = SCHEMA.get(key)
        if option is None:
            raise InvalidSetting(f"unknown setting {key!r}")
        self._values[key] = _coerce(option, value)

    def reset(self, key: str) -> None:
        if key not in SCHEMA:
            raise InvalidSetting(f"unknown setting {key!r}")
        self._values.pop(key, None)

    def items(self) -> list[tuple[str, Any]]:
        return [(key, getattr(self, key)) for key in SCHEMA]

    def to_dict(self) -> dict[str, Any]:
        """Only the values that differ from the defaults are stored."""
        return dict(sorted(self._values.items()))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Settings) and self.items() == other.items()
