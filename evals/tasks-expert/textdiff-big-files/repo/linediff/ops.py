"""Edit scripts: what diff returns and what the hunk writer reads."""

from typing import NamedTuple

KEEP = "keep"
DELETE = "delete"
INSERT = "insert"


class Op(NamedTuple):
    """One run of the script: lines old[old_start:old_end] and new[new_start:new_end].

    A keep run covers the same number of lines on both sides, a delete run covers only old
    lines (new_start == new_end) and an insert run only new lines (old_start == old_end).
    """

    tag: str
    old_start: int
    old_end: int
    new_start: int
    new_end: int


class ScriptBuilder:
    """Collects a script one step at a time, joining steps of the same kind into runs."""

    def __init__(self) -> None:
        self.ops: list[Op] = []
        self.old = 0
        self.new = 0

    def keep(self, count: int = 1) -> None:
        self._add(KEEP, count, count)

    def delete(self, count: int = 1) -> None:
        self._add(DELETE, count, 0)

    def insert(self, count: int = 1) -> None:
        self._add(INSERT, 0, count)

    def _add(self, tag: str, old: int, new: int) -> None:
        if old == 0 and new == 0:
            return
        start_old, start_new = self.old, self.new
        self.old += old
        self.new += new
        if self.ops and self.ops[-1].tag == tag:
            last = self.ops[-1]
            self.ops[-1] = last._replace(old_end=self.old, new_end=self.new)
        else:
            self.ops.append(Op(tag, start_old, self.old, start_new, self.new))


def edit_count(ops: list[Op]) -> int:
    """How many lines a script deletes and inserts, all told."""
    return sum(
        (op.old_end - op.old_start) + (op.new_end - op.new_start)
        for op in ops
        if op.tag != KEEP
    )
