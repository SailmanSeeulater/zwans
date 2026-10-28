"""A bookmark, and the rules for folder paths."""

from dataclasses import asdict, dataclass
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
    folder: str = ""  # a path like "Dev/Python"; "" is the top level
    added: str = ""  # YYYY-MM-DD, or "" when unknown
    visits: int = 0
    starred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bookmark":
        return cls(**data)


def normalize_folder(text: str) -> str:
    """' Dev / Python/ ' -> 'Dev/Python'. Segments keep their case; empty ones go."""
    return "/".join(segment.strip() for segment in text.split("/") if segment.strip())


def in_folder(folder: str, parent: str) -> bool:
    """True when folder is parent itself or somewhere inside it."""
    return folder == parent or folder.startswith(parent + "/")
