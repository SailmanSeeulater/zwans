"""Format 3 -> 4: folders become tags.

A bookmark in folder "Dev/Python" gets the tags ["dev", "python"]: each folder segment,
lowercased, with runs of spaces turned into one "-", duplicates dropped. A bookmark at the
top level gets no tags.
"""

import copy
from typing import Any


def _tags(folder: str) -> list[str]:
    tags: list[str] = []
    for segment in folder.split("/"):
        tag = "-".join(segment.lower().split())
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def migrate(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    bookmarks = []
    for old in doc["bookmarks"]:
        bookmark = {key: value for key, value in old.items() if key != "folder"}
        bookmark["tags"] = _tags(old["folder"])
        bookmarks.append(bookmark)
    return {"version": 4, "next_id": doc["next_id"], "bookmarks": bookmarks}
