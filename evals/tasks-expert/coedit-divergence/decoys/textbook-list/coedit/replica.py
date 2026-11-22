"""A tempting wrong answer: the textbook replicated growable array. It fixes every bug in
the starting code (indexes that count deleted characters, no tie-break on site, ops that
arrive early or twice, a counter that ignores what it has seen) and keeps its list with the
usual rule for placing an insert: after the character it follows, skip every character
newer than it. That rule reads the tree correctly only when every character is newer than
the one it was typed after, which the README says imported ops don't promise. It passes all
but the tests with such ids."""

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
        self.chars: list[_Char] = []
        self.ids: set[Id] = set()
        self.deleted: set[Id] = set()
        self.waiting: list[Insert] = []

    def text(self) -> str:
        return "".join(c.char for c in self.chars if not c.deleted)

    def _visible(self) -> list[_Char]:
        return [c for c in self.chars if not c.deleted]

    def insert(self, index: int, char: str) -> Insert:
        visible = self._visible()
        if not 0 <= index <= len(visible):
            raise IndexError(index)
        self.counter += 1
        after = visible[index - 1].id if index > 0 else None
        op = Insert(id=(self.counter, self.site), after=after, char=char)
        self.apply(op)
        return op

    def delete(self, index: int) -> Delete:
        visible = self._visible()
        if not 0 <= index < len(visible):
            raise IndexError(index)
        op = Delete(target=visible[index].id)
        self.apply(op)
        return op

    def apply(self, op: Op) -> None:
        if isinstance(op, Delete):
            self.deleted.add(op.target)
            for char in self.chars:
                if char.id == op.target:
                    char.deleted = True
            return
        self.counter = max(self.counter, op.id[0])
        if op.id in self.ids or any(w.id == op.id for w in self.waiting):
            return
        if op.after is not None and op.after not in self.ids:
            self.waiting.append(op)
            return
        self._place(op)
        progress = True
        while progress:
            progress = False
            for waiting in list(self.waiting):
                if waiting.after in self.ids:
                    self.waiting.remove(waiting)
                    self._place(waiting)
                    progress = True

    def _place(self, op: Insert) -> None:
        position = 0
        if op.after is not None:
            position = next(i for i, c in enumerate(self.chars) if c.id == op.after) + 1
        while position < len(self.chars) and self.chars[position].id > op.id:
            position += 1
        self.chars.insert(position, _Char(op.id, op.char, op.id in self.deleted))
        self.ids.add(op.id)
