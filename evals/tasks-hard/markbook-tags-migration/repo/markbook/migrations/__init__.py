"""Migrations: how a document written by an older markbook is brought up to date.

Each migration lives in its own module, takes a document of version N and returns a NEW
document of version N + 1. It never changes the document it was given. It is registered in
MIGRATIONS under N.

Migrations never import from the rest of markbook: a migration must keep doing exactly
what it did when it was written, whatever happens to the model or the schema later. If it
needs a helper, it gets its own copy.
"""

from collections.abc import Callable
from typing import Any

from ..schema import CURRENT_VERSION
from . import m001_categories_to_folders, m002_stars_and_ids

Document = dict[str, Any]

MIGRATIONS: dict[int, Callable[[Document], Document]] = {
    1: m001_categories_to_folders.migrate,
    2: m002_stars_and_ids.migrate,
}


class MigrationError(ValueError):
    pass


def version_of(doc: Any) -> int:
    if not isinstance(doc, dict) or type(doc.get("version")) is not int or doc["version"] < 1:
        raise MigrationError("this is not a markbook file (no version)")
    return doc["version"]


def migrate(doc: Document) -> Document:
    """Bring doc up to CURRENT_VERSION. Returns doc itself when it is already current."""
    version = version_of(doc)
    if version > CURRENT_VERSION:
        raise MigrationError(
            f"this file was written by a newer markbook (format {version}); "
            f"this one only knows up to format {CURRENT_VERSION}"
        )
    while version < CURRENT_VERSION:
        try:
            step = MIGRATIONS[version]
        except KeyError:
            raise MigrationError(f"no migration from format {version}") from None
        doc = step(doc)
        if doc.get("version") != version + 1:
            raise MigrationError(
                f"the migration from format {version} did not produce format {version + 1}"
            )
        version += 1
    return doc
