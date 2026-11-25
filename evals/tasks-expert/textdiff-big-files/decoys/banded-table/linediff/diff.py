"""Working out the edit script that turns one list of lines into another.

First the number of edits D, from a forward search that keeps the furthest point reached
on each diagonal. A script with D edits never strays more than D diagonals from either
corner, so the table of remaining costs is only filled in inside that band, then walked
from the top.
"""

from collections.abc import Sequence

from linediff.ops import Op, ScriptBuilder

_FAR = 1 << 62


def diff(old: Sequence, new: Sequence) -> list[Op]:
    """The minimal edit script from `old` to `new`, chosen as the README describes."""
    n, m = len(old), len(new)
    d = _distance(old, new, n, m)

    # rest[x] holds the fewest edits that turn old[x:] into new[y:] for y in lo[x]..hi[x].
    lo = [max(0, x - d, x - (n - m) - d) for x in range(n + 1)]
    hi = [min(m, x + d, x - (n - m) + d) for x in range(n + 1)]
    rest: list[list[int]] = [[] for _ in range(n + 1)]

    def cost(x: int, y: int) -> int:
        if lo[x] <= y <= hi[x]:
            return rest[x][y - lo[x]]
        return _FAR

    for x in range(n, -1, -1):
        row = [_FAR] * (hi[x] - lo[x] + 1)
        rest[x] = row
        for y in range(hi[x], lo[x] - 1, -1):
            if x == n:
                value = m - y
            elif y == m:
                value = n - x
            else:
                value = 1 + min(cost(x + 1, y), cost(x, y + 1))
                corner = cost(x + 1, y + 1)
                if corner < value and old[x] == new[y]:
                    value = corner
            row[y - lo[x]] = value

    script = ScriptBuilder()
    x = y = 0
    while x < n or y < m:
        here = cost(x, y)
        if x < n and cost(x + 1, y) + 1 == here:
            script.delete()
            x += 1
        elif x < n and y < m and cost(x + 1, y + 1) == here and old[x] == new[y]:
            script.keep()
            x += 1
            y += 1
        else:
            script.insert()
            y += 1
    return script.ops


def _distance(a: Sequence, b: Sequence, n: int, m: int) -> int:
    """The fewest edits that turn a into b."""
    if n == 0 or m == 0:
        return n + m
    offset = n + m + 1
    far = [0] * (2 * offset + 1)
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
