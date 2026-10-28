from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from notes.util import slugify

if TYPE_CHECKING:
    from notes.storage import Store


@dataclass
class Note:
    title: str
    body: str = ""
    tags: set[str] = field(default_factory=set)

    @property
    def slug(self) -> str:
        return slugify(self.title)

    def to_markdown(self) -> str:
        from notes.render import render_note

        return render_note(self)

    def save(self, store: Store) -> None:
        store.put(self)
