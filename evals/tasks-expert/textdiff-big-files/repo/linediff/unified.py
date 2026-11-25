"""Writing an edit script out as a unified diff."""

from collections.abc import Sequence

from linediff.diff import diff
from linediff.ops import KEEP, Op


def unified(
    old: Sequence[str],
    new: Sequence[str],
    context: int = 3,
    old_name: str = "old",
    new_name: str = "new",
) -> str:
    """A unified diff from `old` to `new`, or "" when they are the same."""
    if context < 0:
        raise ValueError("context can't be negative")
    hunks = _group(diff(old, new), context)
    if not hunks:
        return ""
    out = [f"--- {old_name}\n", f"+++ {new_name}\n"]
    for hunk in hunks:
        out.extend(_write(hunk, old, new))
    return "".join(out)


def _group(ops: list[Op], context: int) -> list[list[Op]]:
    """The runs of each hunk: changes plus up to `context` kept lines on either side,
    with changes no more than 2 * context kept lines apart sharing a hunk."""
    hunks: list[list[Op]] = []
    current: list[Op] = []
    for index, op in enumerate(ops):
        if op.tag != KEEP:
            current.append(op)
            continue
        size = op.old_end - op.old_start
        last = index == len(ops) - 1
        if current and not last and size <= 2 * context:
            current.append(op)
            continue
        take = min(size, context)
        if current:
            if take:
                current.append(op._replace(old_end=op.old_start + take, new_end=op.new_start + take))
            hunks.append(current)
            current = []
        if not last and take:
            current = [op._replace(old_start=op.old_end - take, new_start=op.new_end - take)]
    if current:
        hunks.append(current)
    return hunks


def _write(hunk: list[Op], old: Sequence[str], new: Sequence[str]) -> list[str]:
    old_start, new_start = hunk[0].old_start, hunk[0].new_start
    old_len = hunk[-1].old_end - old_start
    new_len = hunk[-1].new_end - new_start
    out = [f"@@ -{_where(old_start, old_len)} +{_where(new_start, new_len)} @@\n"]
    for op in hunk:
        if op.tag == KEEP:
            out.extend(f" {line}\n" for line in old[op.old_start : op.old_end])
        elif op.old_end > op.old_start:
            out.extend(f"-{line}\n" for line in old[op.old_start : op.old_end])
        else:
            out.extend(f"+{line}\n" for line in new[op.new_start : op.new_end])
    return out


def _where(start: int, length: int) -> str:
    # A range of no lines is written as the line before it (0 at the top of the file).
    return f"{start + 1 if length else start},{length}"
