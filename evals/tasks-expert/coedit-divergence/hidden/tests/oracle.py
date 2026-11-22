"""The text a set of ops defines, worked out from scratch, for the tests to compare with."""

from coedit import Delete, Id, Insert, Op


def text_of(ops: list[Op]) -> str:
    """The README's definition: the tree of inserts read depth-first, children newest first,
    deleted characters left out. Inserts whose chain back to the start is incomplete, and
    deletes of them, haven't taken effect."""
    chars: dict[Id, str] = {}
    children: dict[Id | None, set[Id]] = {}
    deleted: set[Id] = set()
    for op in ops:
        if isinstance(op, Insert):
            chars[op.id] = op.char
            children.setdefault(op.after, set()).add(op.id)
        elif isinstance(op, Delete):
            deleted.add(op.target)
    out: list[str] = []
    stack = sorted(children.get(None, ()))
    while stack:
        id = stack.pop()
        if id not in deleted:
            out.append(chars[id])
        stack.extend(sorted(children.get(id, ())))
    return "".join(out)
