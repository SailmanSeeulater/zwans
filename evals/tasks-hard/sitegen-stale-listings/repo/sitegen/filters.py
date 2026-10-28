"""Template filters. Each takes the value, the site config, and an optional argument."""

import html
from collections.abc import Callable
from datetime import date, datetime

from sitegen.slugify import slugify


class Markup(str):
    """Text that is already HTML, so templates must not escape it again."""


def _date(value: object, settings: object, fmt: object = None) -> str:
    if not isinstance(value, (date, datetime)):
        return "" if value is None else str(value)
    pattern = fmt if isinstance(fmt, str) else getattr(settings, "date_format", "%Y-%m-%d")
    return value.strftime(pattern)


def _isodate(value: object, settings: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return ""


def _safe(value: object, settings: object) -> Markup:
    return value if isinstance(value, Markup) else Markup("" if value is None else str(value))


def _escape(value: object, settings: object) -> Markup:
    return Markup(html.escape("" if value is None else str(value)))


def _truncate(value: object, settings: object, words: object = 30) -> str:
    parts = ("" if value is None else str(value)).split()
    limit = words if isinstance(words, int) else 30
    if len(parts) <= limit:
        return " ".join(parts)
    return " ".join(parts[:limit]) + " …"


def _join(value: object, settings: object, separator: object = ", ") -> str:
    if value is None:
        return ""
    return str(separator).join(str(item) for item in value)  # type: ignore[attr-defined]


def _length(value: object, settings: object) -> int:
    try:
        return len(value)  # type: ignore[arg-type]
    except TypeError:
        return 0


def _default(value: object, settings: object, fallback: object = "") -> object:
    return value if value else fallback


def _absolute(value: object, settings: object) -> str:
    base = getattr(settings, "base_url", "/")
    return base.rstrip("/") + "/" + str(value or "").lstrip("/")


def _relative(value: object, settings: object) -> str:
    return "/" + str(value or "").lstrip("/")


def _plural(value: object, settings: object, word: object = "") -> str:
    count = value if isinstance(value, int) else 0
    noun = str(word)
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


FILTERS: dict[str, Callable[..., object]] = {
    "date": _date,
    "isodate": _isodate,
    "safe": _safe,
    "escape": _escape,
    "truncate": _truncate,
    "join": _join,
    "length": _length,
    "default": _default,
    "absolute": _absolute,
    "url": _relative,
    "plural": _plural,
    "slug": lambda value, settings: slugify(str(value or "")),
    "upper": lambda value, settings: str(value or "").upper(),
    "lower": lambda value, settings: str(value or "").lower(),
}
