"""Format 2 -> 3: bookmarks can be starred, and the file remembers the next id to hand out.

Before format 3 a removed bookmark's id could be handed out again; next_id stops that.
"""

import copy
from typing import Any


def migrate(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    bookmarks = [{**bookmark, "starred": False} for bookmark in doc["bookmarks"]]
    next_id = max((bookmark["id"] for bookmark in bookmarks), default=0) + 1
    return {"version": 3, "next_id": next_id, "bookmarks": bookmarks}
