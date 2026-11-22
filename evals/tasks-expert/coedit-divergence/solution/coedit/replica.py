"""One person's copy of the document."""

import bisect

from coedit.ops import Delete, Id, Insert, Op


class Replica:
    def __init__(self, site: str) -> None:
        self.site = site
        self.counter = 0  # the highest counter seen, so a new character is newer than all
        self.chars: dict[Id, str] = {}
        # Each character's children, oldest first; None is the start of the text.
        self.children: dict[Id | None, list[Id]] = {None: []}
        self.deleted: set[Id] = set()  # deletes seen, some maybe of characters still to come
        self.waiting: dict[Id, list[Insert]] = {}  # inserts after a character still to come
        self.waiting_ids: set[Id] = set()

    def text(self) -> str:
        return "".join(self.chars[id] for id in self._visible())

    def _order(self) -> list[Id]:
        """Every character in document order: the tree read depth-first, newest child
        first. Iterative, since typing a long text makes the tree as deep as the text."""
        order: list[Id] = []
        stack = list(self.children[None])  # oldest first, so the newest is popped first
        while stack:
            id = stack.pop()
            order.append(id)
            stack.extend(self.children.get(id, ()))
        return order

    def _visible(self) -> list[Id]:
        return [id for id in self._order() if id not in self.deleted]

    # -- this person's own edits: change the copy and return the op to send to the others

    def insert(self, index: int, char: str) -> Insert:
        """Type `char` so that it becomes text()[index]."""
        visible = self._visible()
        if not 0 <= index <= len(visible):
            raise IndexError(f"index {index} is outside a text of {len(visible)} characters")
        self.counter += 1
        after = visible[index - 1] if index > 0 else None
        op = Insert(id=(self.counter, self.site), after=after, char=char)
        self.apply(op)
        return op

    def delete(self, index: int) -> Delete:
        """Remove text()[index]."""
        visible = self._visible()
        if not 0 <= index < len(visible):
            raise IndexError(f"index {index} is outside a text of {len(visible)} characters")
        op = Delete(target=visible[index])
        self.apply(op)
        return op

    # -- edits from anyone

    def apply(self, op: Op) -> None:
        if isinstance(op, Delete):
            self.deleted.add(op.target)  # takes effect whenever the character is there
            return
        self.counter = max(self.counter, op.id[0])
        if op.id in self.chars or op.id in self.waiting_ids:
            return  # seen before
        if op.after is not None and op.after not in self.chars:
            self.waiting.setdefault(op.after, []).append(op)
            self.waiting_ids.add(op.id)
            return
        ready = [op]
        while ready:
            insert = ready.pop()
            self.waiting_ids.discard(insert.id)
            self.chars[insert.id] = insert.char
            self.children[insert.id] = []
            bisect.insort(self.children[insert.after], insert.id)
            ready.extend(self.waiting.pop(insert.id, ()))
