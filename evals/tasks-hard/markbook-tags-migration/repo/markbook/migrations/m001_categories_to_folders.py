"""Format 1 -> 2: categories become folders, and bookmarks get ids and a visit count.

Format 1 bookmarks had a "category" like "Dev > Python". Format 2 calls it "folder" and
writes it as a path, "Dev/Python". Ids are handed out in file order, starting at 1.
"""

import copy
from typing import Any


def _folder(category: str) -> str:
    return "/".join(part.strip() for part in category.split(">") if part.strip())


def migrate(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    bookmarks = []
    for number, old in enumerate(doc["bookmarks"], start=1):
        bookmarks.append(
            {
                "id": number,
                "url": old["url"],
                "title": old.get("title", ""),
                "folder": _folder(old.get("category", "")),
                "added": old.get("added", ""),
                "visits": 0,
            }
        )
    return {"version": 2, "bookmarks": bookmarks}
