"""diff against the README: the exact minimal script it describes, on small random files
and on big ones, within the comparison and memory limits of "Big files"."""

import itertools
import random
import tracemalloc

import oracle
import pytest

from linediff import apply, diff, unified


class OverBudget(AssertionError):
    pass


class Line:
    """A line that counts every == and stops the test once a budget is used up. Like
    any class that defines __eq__ only, it can't be hashed."""

    compared = 0
    budget: float = float("inf")

    __slots__ = ("text",)
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, text: str) -> None:
        self.text = text

    def __eq__(self, other: object) -> bool:
        Line.compared += 1
        if Line.compared > Line.budget:
            raise OverBudget(f"more than {Line.budget} comparisons")
        return self.text == other.text  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return repr(self.text)


def lines(texts: list[str]) -> list[Line]:
    return [Line(text) for text in texts]


def limit(n: int, m: int, d: int) -> int:
    return 4 * (n + m + 1) * (d + 1)


def run(old: list[str], new: list[str], budget: float = float("inf")) -> tuple[list[tuple], int]:
    Line.compared, Line.budget = 0, budget
    try:
        ops = diff(lines(old), lines(new))
    finally:
        spent, Line.budget = Line.compared, float("inf")
    return [tuple(op) for op in ops], spent


COMMON = ["", "}", "{", "    return None", "    pass", "else:", "# ----", "end"]


def big_pair(seed: int, n: int, edits: int, shared: float = 0.3) -> tuple[list[str], list[str], int]:
    """A file of n lines, a share of them repeated boilerplate, and a copy with `edits`
    lines deleted or inserted here and there. Returns both and the number of edits made,
    which is at least the minimal script's."""
    rng = random.Random(seed)
    old = [
        rng.choice(COMMON) if rng.random() < shared else f"line {rng.randrange(2 * n)}"
        for _ in range(n)
    ]
    new = list(old)
    made = 0
    while made < edits:
        at = rng.randrange(len(new) + 1)
        size = min(rng.randint(1, 3), edits - made)
        if rng.random() < 0.45 and at + size <= len(new):
            del new[at : at + size]
        else:
            new[at:at] = [
                rng.choice(COMMON) if rng.random() < 0.5 else f"new {rng.randrange(10**6)}"
                for _ in range(size)
            ]
        made += size
    return old, new, made


# -- small files: exactly the README's script


@pytest.mark.parametrize("seed", range(60))
def test_small_files_get_exactly_the_readme_script(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(12):
        alphabet = "abcde"[: rng.randint(2, 5)]
        old = [rng.choice(alphabet) for _ in range(rng.randint(0, 24))]
        new = [rng.choice(alphabet) for _ in range(rng.randint(0, 24))]
        if rng.random() < 0.3:  # a near copy, the usual case
            new = list(old)
            for _ in range(rng.randint(1, 4)):
                at = rng.randrange(len(new) + 1)
                if rng.random() < 0.5 and at < len(new):
                    del new[at]
                else:
                    new.insert(at, rng.choice(alphabet))
        want = oracle.script(old, new)

        got, spent = run(old, new, budget=limit(len(old), len(new), oracle.edits(want)))

        oracle.check_script(got, old, new)
        assert oracle.edits(got) == oracle.edits(want), (
            f"not minimal: {oracle.edits(got)} edits where {oracle.edits(want)} will do. "
            f"old={old} new={new}"
        )
        assert got == want, f"old={old} new={new}: got {got}, the README's script is {want}"


def test_files_with_nothing_in_common() -> None:
    old = [f"old {i}" for i in range(300)]
    new = [f"new {i}" for i in range(250)]

    got, _ = run(old, new, budget=limit(300, 250, 550))

    assert got == [("delete", 0, 300, 0, 0), ("insert", 300, 300, 0, 250)]


def test_runs_of_one_repeated_line() -> None:
    old = ["x"] * 40 + ["y"] + ["x"] * 40
    new = ["x"] * 70

    got, _ = run(old, new, budget=limit(81, 70, 11))

    assert got == oracle.script(old, new)


# -- big files: same script, within the comparison budget


@pytest.mark.parametrize(("seed", "n", "edits"), [(1, 20000, 12), (3, 30000, 30)])
def test_big_files_with_few_changes(seed: int, n: int, edits: int) -> None:
    old, new, made = big_pair(seed, n, edits)
    want = oracle.script(old, new, band=made)
    d = oracle.edits(want)

    got, spent = run(old, new, budget=limit(len(old), len(new), d))

    assert oracle.edits(got) == d, f"not minimal: {oracle.edits(got)} edits where {d} will do"
    assert got == want, "a minimal script, but not the one the README picks"
    assert spent <= limit(len(old), len(new), d)


def test_identical_big_files_cost_a_pass_over_them() -> None:
    old = [f"line {i % 500}" for i in range(40000)]

    got, spent = run(old, list(old), budget=limit(40000, 40000, 0))

    assert got == [("keep", 0, 40000, 0, 40000)]


@pytest.mark.parametrize(("seed", "n", "edits"), [(4, 1500, 500), (5, 3000, 300)])
def test_many_changes(seed: int, n: int, edits: int) -> None:
    old, new, made = big_pair(seed, n, edits, shared=0.5)
    want = oracle.script(old, new, band=made)
    d = oracle.edits(want)

    got, spent = run(old, new, budget=limit(len(old), len(new), d))

    assert got == want
    assert spent <= limit(len(old), len(new), d)


# -- memory


class QuietLine:
    """A line that stops the test once a budget of comparisons is used up, without
    allocating anything per comparison (so tracemalloc stays quick)."""

    ticks = itertools.repeat(None, 0)

    __slots__ = ("text",)
    __hash__ = None  # type: ignore[assignment]

    def __init__(self, text: str) -> None:
        self.text = text

    def __eq__(self, other: object) -> bool:
        if next(QuietLine.ticks, False) is False:
            raise OverBudget("over the comparison budget")
        return self.text == other.text  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("seed", "n", "edits"), [(7, 1200, 400), (8, 2500, 250)]
)
def test_memory_grows_with_the_files_not_their_product(seed: int, n: int, edits: int) -> None:
    old, new, made = big_pair(seed, n, edits, shared=0.4)
    a, b = [QuietLine(t) for t in old], [QuietLine(t) for t in new]
    QuietLine.ticks = itertools.repeat(None, limit(len(old), len(new), made))

    tracemalloc.start()
    try:
        diff(a, b)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    allowed = 400 * (len(old) + len(new)) + 2**20
    assert peak <= allowed, f"diff peaked at {peak} bytes; the README allows {allowed}"


# -- what the scripts are used for


class QuietText(str):
    """A text line with the same comparison budget as QuietLine."""

    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if next(QuietLine.ticks, False) is False:
            raise OverBudget("over the comparison budget")
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


@pytest.mark.parametrize("seed", range(2))
def test_a_patch_of_a_big_file_rebuilds_it(seed: int) -> None:
    old, new, made = big_pair(10 + seed, 15000, 25)
    a, b = [QuietText(t) for t in old], [QuietText(t) for t in new]

    for context in (0, 3):
        QuietLine.ticks = itertools.repeat(None, limit(len(old), len(new), made))
        patch = unified(a, b, context)
        assert apply(patch, old) == new


def test_hunks_follow_the_readme_script() -> None:
    old = ["{", "a", "}", "", "{", "b", "}"]
    new = ["{", "b", "}"]

    assert unified(old, new, context=1) == (
        "--- old\n+++ new\n@@ -1,5 +1,1 @@\n-{\n-a\n-}\n-\n {\n"
    )
