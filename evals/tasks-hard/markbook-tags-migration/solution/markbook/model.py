"""A bookmark, and the rules for tags."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any


class MarkbookError(Exception):
    """Something the user asked for that cannot be done; the CLI prints it and exits 1."""


class NotFound(MarkbookError):
    pass


class DuplicateUrl(MarkbookError):
    pass


@dataclass
class Bookmark:
    id: int
    url: str
    title: str
    tags: list[str] = field(default_factory=list)  # normalised, no duplicates, in the order added
    added: str = ""  # YYYY-MM-DD, or "" when unknown
    visits: int = 0
    starred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bookmark":
        return cls(**{**data, "tags": list(data["tags"])})


def normalize_tag(text: str) -> str:
    """'Machine  Learning ' -> 'machine-learning': lowercase, runs of spaces become one '-'."""
    return "-".join(text.lower().split())


def normalize_tags(texts: Iterable[str]) -> list[str]:
    """Normalise each tag, dropping empty ones and duplicates, keeping the first order."""
    tags: list[str] = []
    for text in texts:
        tag = normalize_tag(text)
        if tag and tag not in tags:
            tags.append(tag)
    return tags
