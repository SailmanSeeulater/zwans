"""One person's copy of the document."""

from dataclasses import dataclass

from coedit.ops import Delete, Id, Insert, Op


@dataclass
class _Char:
    id: Id
    char: str
    deleted: bool = False


class Replica:
    def __init__(self, site: str) -> None:
        self.site = site
        self.counter = 0
        self.chars: list[_Char] = []  # in document order, deleted ones included

    def text(self) -> str:
        return "".join(c.char for c in self.chars if not c.deleted)

    # -- this person's own edits: change the copy and return the op to send to the others

    def insert(self, index: int, char: str) -> Insert:
        """Type `char` so that it becomes text()[index]."""
        self.counter += 1
        after = self.chars[index - 1].id if index > 0 else None
        op = Insert(id=(self.counter, self.site), after=after, char=char)
        self.apply(op)
        return op

    def delete(self, index: int) -> Delete:
        """Remove text()[index]."""
        op = Delete(target=self.chars[index].id)
        self.apply(op)
        return op

    # -- edits from anyone

    def apply(self, op: Op) -> None:
        if isinstance(op, Delete):
            for char in self.chars:
                if char.id == op.target:
                    char.deleted = True
            return
        position = 0
        if op.after is not None:
            position = len(self.chars)
            for index, char in enumerate(self.chars):
                if char.id == op.after:
                    position = index + 1
        # Newer characters typed at the same place come first.
        while position < len(self.chars) and self.chars[position].id[0] > op.id[0]:
            position += 1
        self.chars.insert(position, _Char(op.id, op.char))
