"""A slow, obviously-right diff for the tests to compare against, following the README.

It works out, for every point (x, y), the fewest edits that turn old[x:] into new[y:], and
then walks from the top taking a deletion whenever a minimal script can still start with
one, else a kept line, else an insertion. Taking the deletion first keeps the walk as high
as any minimal script can be at every column, which is the README's choice.

`script(old, new, band=None)`: with a band, only diagonals within `band` of both corners are
worked out, which is exact when the files need at most `band` edits and lets the tests
check big files with few changes.
"""

from collections.abc import Sequence


def script(old: Sequence, new: Sequence, band: int | None = None) -> list[tuple]:
    n, m = len(old), len(new)
    far = n + m + 1

    def inside(x: int, y: int) -> bool:
        return band is None or (abs(x - y) <= band and abs((n - x) - (m - y)) <= band)

    rest: dict[tuple[int, int], int] | list[list[int]]
    rest = {}
    for x in range(n, -1, -1):
        if band is None:
            ys = range(m, -1, -1)
        else:
            ys = range(min(m, x + band), max(0, x - band) - 1, -1)
        for y in ys:
            if not inside(x, y):
                continue
            if x == n:
                rest[x, y] = m - y
            elif y == m:
                rest[x, y] = n - x
            elif old[x] == new[y]:
                rest[x, y] = rest.get((x + 1, y + 1), far)
            else:
                rest[x, y] = 1 + min(rest.get((x + 1, y), far), rest.get((x, y + 1), far))

    steps: list[str] = []
    x = y = 0
    while x < n or y < m:
        here = rest[x, y]
        if x < n and rest.get((x + 1, y), far) + 1 == here:
            steps.append("delete")
            x += 1
        elif x < n and y < m and old[x] == new[y] and rest.get((x + 1, y + 1), far) == here:
            steps.append("keep")
            x += 1
            y += 1
        else:
            steps.append("insert")
            y += 1
    return runs(steps)


def runs(steps: list[str]) -> list[tuple]:
    """Steps joined into (tag, old_start, old_end, new_start, new_end) runs."""
    out: list[list] = []
    x = y = 0
    for step in steps:
        dx = 1 if step in ("keep", "delete") else 0
        dy = 1 if step in ("keep", "insert") else 0
        if out and out[-1][0] == step:
            out[-1][2] += dx
            out[-1][4] += dy
        else:
            out.append([step, x, x + dx, y, y + dy])
        x += dx
        y += dy
    return [tuple(run) for run in out]


def edits(ops: Sequence) -> int:
    return sum((op[2] - op[1]) + (op[4] - op[3]) for op in ops if op[0] != "keep")


def check_script(ops: Sequence, old: Sequence, new: Sequence) -> None:
    """That `ops` is a well-formed script from old to new (whatever its choices)."""
    x = y = 0
    last = None
    for op in ops:
        tag, x0, x1, y0, y1 = op
        assert tag in ("keep", "delete", "insert"), op
        assert (x0, y0) == (x, y), f"run {op} doesn't start where the last one ended"
        assert tag != last, f"two {tag} runs in a row at {op}"
        if tag == "keep":
            assert x1 - x0 == y1 - y0 > 0, op
            for i in range(x1 - x0):
                assert old[x0 + i] == new[y0 + i], f"{op} keeps lines that differ"
        elif tag == "delete":
            assert x1 > x0 and y1 == y0, op
        else:
            assert y1 > y0 and x1 == x0, op
        x, y, last = x1, y1, tag
    assert (x, y) == (len(old), len(new)), "the script doesn't cover both files"
