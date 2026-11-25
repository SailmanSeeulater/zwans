"""Working out the edit script that turns one list of lines into another.

The script is a path through the grid of (lines of old used, lines of new used): a
deletion steps right, an insertion steps down, a kept line steps diagonally. The README's
script is the minimal path that, at every column, is as high up as a minimal path can be.

1. The number of edits D comes from a forward search that keeps only the furthest point
   reached on each diagonal (linear memory, O((N + M) * D) comparisons).
2. The path is then found by splitting the old lines in half: costs from the start and
   from the end are worked out up to the middle column inside the band of diagonals a
   path with D edits can use, the path's point on that column is the smallest y where
   the two add up to D, and each half is solved the same way with its own, smaller D.
"""

from collections.abc import Sequence

from linediff.ops import Op, ScriptBuilder

_FAR = 1 << 62


def diff(old: Sequence, new: Sequence) -> list[Op]:
    """The minimal edit script from `old` to `new`, chosen as the README describes."""
    n, m = len(old), len(new)
    script = ScriptBuilder()
    edits = _distance(old, new, n, m)
    _solve(old, new, 0, n, 0, m, edits, script)
    return script.ops


def _distance(a: Sequence, b: Sequence, n: int, m: int) -> int:
    """The fewest edits that turn a into b."""
    if n == 0 or m == 0:
        return n + m
    offset = n + m + 1
    far = [0] * (2 * offset + 1)  # furthest x reached on each diagonal k = x - y
    for d in range(n + m + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and far[offset + k - 1] < far[offset + k + 1]):
                x = far[offset + k + 1]
            else:
                x = far[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            far[offset + k] = x
            if x >= n and y >= m:
                return d
    return n + m


def _solve(
    a: Sequence, b: Sequence, x0: int, x1: int, y0: int, y1: int, d: int, out: ScriptBuilder
) -> None:
    """Append the README's script for a[x0:x1] -> b[y0:y1], which needs d edits."""
    n, m = x1 - x0, y1 - y0
    if d == 0:
        out.keep(n)
        return
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

    half = n // 2
    mid = x0 + half
    delta = n - m
    low, high = (delta - d) // 2, (delta + d) // 2  # the diagonals a d-edit path can use
    f_lo, forward = _band(a, x0, 1, b, y0, 1, half, m, low, high)
    b_lo, backward = _band(a, x1 - 1, -1, b, y1 - 1, -1, n - half, m, low, high)

    for j in range(f_lo, f_lo + len(forward)):  # j = y - y0, smallest first
        back = m - j - b_lo
        if 0 <= back < len(backward) and forward[j - f_lo] + backward[back] == d:
            y = y0 + j
            _solve(a, b, x0, mid, y0, y, forward[j - f_lo], out)
            _solve(a, b, mid, x1, y, y1, backward[back], out)
            return
    raise AssertionError("no split point")  # unreachable when d is right


def _band(
    a: Sequence,
    a_at: int,
    a_step: int,
    b: Sequence,
    b_at: int,
    b_step: int,
    rows: int,
    m: int,
    low: int,
    high: int,
) -> tuple[int, list[int]]:
    """Fewest edits from the corner to each point of row `rows`, inside diagonals
    low..high (diagonal = row - column). Line i of the sub-problem is a[a_at + a_step*i],
    line j is b[b_at + b_step*j]. Returns the first column kept and the costs from there.
    """
    lo, hi = max(0, -high), min(m, -low)
    row = list(range(lo, hi + 1))
    for i in range(1, rows + 1):
        new_lo, new_hi = max(0, i - high), min(m, i - low)
        new = [_FAR] * (new_hi - new_lo + 1)
        line = a[a_at + a_step * (i - 1)]
        for j in range(new_lo, new_hi + 1):
            best = row[j - lo] + 1 if lo <= j <= hi else _FAR
            if j > new_lo:
                left = new[j - 1 - new_lo] + 1
                if left < best:
                    best = left
            if lo <= j - 1 <= hi:
                corner = row[j - 1 - lo]
                if corner < best and line == b[b_at + b_step * (j - 1)]:
                    best = corner
            new[j - new_lo] = best
        row, lo, hi = new, new_lo, new_hi
    return lo, row
