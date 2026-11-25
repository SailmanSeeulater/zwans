"""Comparing revisions."""

from __future__ import annotations

import difflib

from .models import Revision
from .textutil import word_count


def diff(old: Revision, new: Revision, title: str = "") -> str:
    """A unified diff between two revisions of a page."""
    name = title or "page"
    return "".join(
        difflib.unified_diff(
            old.body.splitlines(keepends=True),
            new.body.splitlines(keepends=True),
            fromfile=f"{name} (revision {old.number})",
            tofile=f"{name} (revision {new.number})",
        )
    )


def auto_summary(old_body: str, new_body: str) -> str:
    """What an edit did, when the author didn't say: "+12 words", "-3 words", "reworded"."""
    delta = word_count(new_body) - word_count(old_body)
    if delta > 0:
        return f"+{delta} words"
    if delta < 0:
        return f"{delta} words"
    return "reworded"


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def authors(revisions: list[Revision]) -> list[str]:
    """Everyone who wrote a revision, most revisions first."""
    counts: dict[str, int] = {}
    for revision in revisions:
        if revision.author:
            counts[revision.author] = counts.get(revision.author, 0) + 1
    return sorted(counts, key=lambda a: (-counts[a], a))
