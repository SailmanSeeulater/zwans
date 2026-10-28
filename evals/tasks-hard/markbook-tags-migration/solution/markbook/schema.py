"""The current file format, and the check every document passes before it is used or saved.

Older versions of the format are only ever seen by the migrations (markbook/migrations/),
which bring a document up to CURRENT_VERSION before validate() looks at it. The history of
the format is in docs/format.md.
"""

import re
from typing import Any

from .model import normalize_tag
from .urls import is_web_url

CURRENT_VERSION = 4

TOP_LEVEL_KEYS = {"version", "next_id", "bookmarks"}
BOOKMARK_FIELDS: dict[str, type] = {
    "id": int,
    "url": str,
    "title": str,
    "tags": list,
    "added": str,
    "visits": int,
    "starred": bool,
}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SchemaError(ValueError):
    pass


def validate(doc: Any) -> None:
    """Raise SchemaError, naming the first thing wrong, unless doc is a valid current document."""
    if not isinstance(doc, dict):
        raise SchemaError("the document should be a JSON object")
    if set(doc) != TOP_LEVEL_KEYS:
        raise SchemaError(
            f"the document should have exactly the keys {sorted(TOP_LEVEL_KEYS)}, not {sorted(doc)}"
        )
    if doc["version"] != CURRENT_VERSION:
        raise SchemaError(f"version should be {CURRENT_VERSION}, not {doc['version']!r}")
    if type(doc["next_id"]) is not int or doc["next_id"] < 1:
        raise SchemaError("next_id should be a positive whole number")
    if not isinstance(doc["bookmarks"], list):
        raise SchemaError("bookmarks should be a list")

    seen: set[int] = set()
    for position, bookmark in enumerate(doc["bookmarks"]):
        where = f"bookmarks[{position}]"
        if not isinstance(bookmark, dict):
            raise SchemaError(f"{where} should be an object")
        if set(bookmark) != set(BOOKMARK_FIELDS):
            raise SchemaError(
                f"{where} should have exactly the keys {sorted(BOOKMARK_FIELDS)}, not {sorted(bookmark)}"
            )
        for name, kind in BOOKMARK_FIELDS.items():
            # type() rather than isinstance(): True is an int, but not a valid id.
            if type(bookmark[name]) is not kind:
                raise SchemaError(f"{where}.{name} should be a {kind.__name__}")
        if not 1 <= bookmark["id"] < doc["next_id"]:
            raise SchemaError(f"{where}.id should be between 1 and next_id - 1")
        if bookmark["id"] in seen:
            raise SchemaError(f"{where}.id {bookmark['id']} is used twice")
        seen.add(bookmark["id"])
        if not is_web_url(bookmark["url"]):
            raise SchemaError(f"{where}.url should be an http(s) URL")
        for tag in bookmark["tags"]:
            if type(tag) is not str or not tag or tag != normalize_tag(tag):
                raise SchemaError(f"{where}.tags: {tag!r} is not a normalised tag")
        if len(set(bookmark["tags"])) != len(bookmark["tags"]):
            raise SchemaError(f"{where}.tags has duplicates")
        if bookmark["added"] and not _DATE.match(bookmark["added"]):
            raise SchemaError(f"{where}.added should be YYYY-MM-DD or empty")
        if bookmark["visits"] < 0:
            raise SchemaError(f"{where}.visits cannot be negative")
