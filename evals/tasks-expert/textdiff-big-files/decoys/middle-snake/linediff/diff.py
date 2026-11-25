"""Working out the edit script that turns one list of lines into another.

Myers' linear-space refinement: search from both corners at once, keeping only the
furthest point reached on each diagonal, until the two searches overlap on a "middle
snake"; then solve the parts before and after it the same way. Within each change the
deleted lines are put before the inserted ones.
"""

from collections.abc import Sequence

from linediff.ops import Op, ScriptBuilder


def diff(old: Sequence, new: Sequence) -> list[Op]:
    """The minimal edit script from `old` to `new`, chosen as the README describes."""
    steps: list[str] = []
    _solve(old, new, 0, len(old), 0, len(new), steps)
    script = ScriptBuilder()
    deletes = inserts = 0
    for step in steps:
        if step == "keep":
            script.delete(deletes)
            script.insert(inserts)
            deletes = inserts = 0
            script.keep()
        elif step == "delete":
            deletes += 1
        else:
            inserts += 1
    script.delete(deletes)
    script.insert(inserts)
    return script.ops


def _solve(a: Sequence, b: Sequence, x0: int, x1: int, y0: int, y1: int, steps: list[str]) -> None:
    n, m = x1 - x0, y1 - y0
    if n == 0:
        steps.extend(["insert"] * m)
        return
    if m == 0:
        steps.extend(["delete"] * n)
        return
    d, (sx, sy, ex, ey) = _middle_snake(a, x0, x1, b, y0, y1)
    if d <= 1:
        # At most one edit: walk the equal lines, make the edit, walk the rest.
        x, y = x0, y0
        while x < x1 and y < y1 and a[x] == b[y]:
            steps.append("keep")
            x += 1
            y += 1
        if x1 - x > y1 - y:
            steps.append("delete")
            x += 1
        elif y1 - y > x1 - x:
            steps.append("insert")
            y += 1
        steps.extend(["keep"] * (x1 - x))
        return
    _solve(a, b, x0, x0 + sx, y0, y0 + sy, steps)
    steps.extend(["keep"] * (ex - sx))
    _solve(a, b, x0 + ex, x1, y0 + ey, y1, steps)


def _middle_snake(a: Sequence, x0: int, x1: int, b: Sequence, y0: int, y1: int):
    n, m = x1 - x0, y1 - y0
    delta = n - m
    odd = delta % 2 != 0
    most = (n + m + 1) // 2
    offset = most + 1
    forward = [0] * (2 * offset + 1)
    backward = [0] * (2 * offset + 1)
    for d in range(most + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and forward[offset + k - 1] < forward[offset + k + 1]):
                x = forward[offset + k + 1]
            else:
                x = forward[offset + k - 1] + 1
            y = x - k
            sx, sy = x, y
            while x < n and y < m and a[x0 + x] == b[y0 + y]:
                x += 1
                y += 1
            forward[offset + k] = x
            if odd and delta - (d - 1) <= k <= delta + (d - 1):
                if x + backward[offset + delta - k] >= n:
                    return 2 * d - 1, (sx, sy, x, y)
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and backward[offset + k - 1] < backward[offset + k + 1]):
                x = backward[offset + k + 1]
            else:
                x = backward[offset + k - 1] + 1
            y = x - k
            sx, sy = x, y
            while x < n and y < m and a[x1 - 1 - x] == b[y1 - 1 - y]:
                x += 1
                y += 1
            backward[offset + k] = x
            if not odd and -d <= delta - k <= d:
                if x + forward[offset + delta - k] >= n:
                    return 2 * d, (n - x, m - y, n - sx, m - sy)
    raise AssertionError("searches never met")
