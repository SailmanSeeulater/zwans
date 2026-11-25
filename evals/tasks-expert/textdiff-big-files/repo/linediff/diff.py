"""Working out the edit script that turns one list of lines into another."""

from collections.abc import Sequence

from linediff.ops import Op, ScriptBuilder


def diff(old: Sequence, new: Sequence) -> list[Op]:
    """The minimal edit script from `old` to `new`, chosen as the README describes."""
    n, m = len(old), len(new)

    # rest[x][y] is the fewest edits that turn old[x:] into new[y:]. Rows are worked out
    # from the bottom up, each from the one below it.
    below = [m - y for y in range(m + 1)]
    rest = [below]
    for x in range(n - 1, -1, -1):
        row = [0] * (m + 1)
        row[m] = n - x
        line = old[x]
        for y in range(m - 1, -1, -1):
            if line == new[y]:
                row[y] = below[y + 1]
            else:
                row[y] = 1 + min(below[y], row[y + 1])
        rest.append(row)
        below = row
    rest.reverse()

    # Walk from the top, taking each step that still leads to a minimal script: a
    # deletion if one does, then a kept line, then an insertion.
    script = ScriptBuilder()
    x = y = 0
    while x < n or y < m:
        here = rest[x][y]
        if x < n and rest[x + 1][y] + 1 == here:
            script.delete()
            x += 1
        elif x < n and y < m and rest[x + 1][y + 1] == here and old[x] == new[y]:
            script.keep()
            x += 1
            y += 1
        else:
            script.insert()
            y += 1
    return script.ops
