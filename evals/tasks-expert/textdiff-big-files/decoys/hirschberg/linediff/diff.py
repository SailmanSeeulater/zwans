"""Working out the edit script that turns one list of lines into another.

Divide and conquer in linear memory: the cost of reaching each point of the middle column
is worked out from the start and from the end one row at a time, keeping only the last
row; the script goes through the first point where the two add up to the best total, and
each half is solved the same way.
"""

from collections.abc import Sequence

from linediff.ops import Op, ScriptBuilder


def diff(old: Sequence, new: Sequence) -> list[Op]:
    """The minimal edit script from `old` to `new`, chosen as the README describes."""
    script = ScriptBuilder()
    _solve(old, new, 0, len(old), 0, len(new), script)
    return script.ops


def _solve(a: Sequence, b: Sequence, x0: int, x1: int, y0: int, y1: int, out: ScriptBuilder) -> None:
    n, m = x1 - x0, y1 - y0
    if n == 0:
        out.insert(m)
        return
    if m == 0:
        out.delete(n)
        return
    if n == 1:
        line = a[x0]
        for y in range(y0, y1):
            if line == b[y]:
                out.insert(y - y0)
                out.keep()
                out.insert(y1 - y - 1)
                return
        out.delete()
        out.insert(m)
        return
    mid = x0 + n // 2
    forward = _costs(a, range(x0, mid), b, range(y0, y1))
    backward = _costs(a, range(x1 - 1, mid - 1, -1), b, range(y1 - 1, y0 - 1, -1))
    best = min(forward[j] + backward[m - j] for j in range(m + 1))
    for j in range(m + 1):
        if forward[j] + backward[m - j] == best:
            _solve(a, b, x0, mid, y0, y0 + j, out)
            _solve(a, b, mid, x1, y0 + j, y1, out)
            return


def _costs(a: Sequence, xs: range, b: Sequence, ys: range) -> list[int]:
    """Fewest edits from the corner to each point of the last row, one row at a time."""
    row = list(range(len(ys) + 1))
    for i, x in enumerate(xs, 1):
        line = a[x]
        new = [i] + [0] * len(ys)
        for j, y in enumerate(ys, 1):
            if line == b[y]:
                new[j] = row[j - 1]
            else:
                new[j] = 1 + min(row[j], new[j - 1])
        row = new
    return row
