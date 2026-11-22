"""The edits replicas send each other."""

from dataclasses import dataclass

Id = tuple[int, str]  # (counter, site): unique for every character ever typed


@dataclass(frozen=True)
class Insert:
    id: Id  # the new character's id
    after: Id | None  # the character it was typed after; None for the start of the text
    char: str


@dataclass(frozen=True)
class Delete:
    target: Id  # the character to remove


Op = Insert | Delete
