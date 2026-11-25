import random

import pytest

from linediff import Op, diff, edit_count


def test_the_readme_example() -> None:
    assert diff(["a", "b", "c", "d"], ["a", "c", "d", "e"]) == [
        Op("keep", 0, 1, 0, 1),
        Op("delete", 1, 2, 1, 1),
        Op("keep", 2, 4, 1, 3),
        Op("insert", 4, 4, 3, 4),
    ]


@pytest.mark.parametrize(
    ("old", "new", "want"),
    [
        ("ab", "cd", [("delete", 0, 2, 0, 0), ("insert", 2, 2, 0, 2)]),
        ("xyx", "x", [("delete", 0, 2, 0, 0), ("keep", 2, 3, 0, 1)]),
        ("x", "xx", [("keep", 0, 1, 0, 1), ("insert", 1, 1, 1, 2)]),
        ("ab", "ba", [("delete", 0, 1, 0, 0), ("keep", 1, 2, 0, 1), ("insert", 2, 2, 1, 2)]),
    ],
)
def test_which_minimal_script(old: str, new: str, want: list[tuple]) -> None:
    assert [tuple(op) for op in diff(list(old), list(new))] == want


def test_empty_and_identical() -> None:
    assert diff([], []) == []
    assert diff(["a"], []) == [Op("delete", 0, 1, 0, 0)]
    assert diff([], ["a", "b"]) == [Op("insert", 0, 0, 0, 2)]
    assert diff(["a", "b"], ["a", "b"]) == [Op("keep", 0, 2, 0, 2)]


class Word:
    """A line that can be compared but not hashed."""

    __hash__ = None  # type: ignore[assignment]

    def __init__(self, text: str) -> None:
        self.text = text

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Word) and self.text == other.text


def test_lines_need_not_be_hashable() -> None:
    old = [Word(t) for t in "the cat sat".split()]
    new = [Word(t) for t in "the dog sat".split()]

    assert edit_count(diff(old, new)) == 2


def brute_force_distance(old: list[str], new: list[str]) -> int:
    rows = [list(range(len(new) + 1))]
    for x, line in enumerate(old, 1):
        row = [x]
        for y, other in enumerate(new, 1):
            if line == other:
                row.append(rows[-1][y - 1])
            else:
                row.append(1 + min(rows[-1][y], row[y - 1]))
        rows.append(row)
    return rows[-1][-1]


@pytest.mark.parametrize("seed", range(20))
def test_scripts_are_minimal_and_cover_both_files(seed: int) -> None:
    rng = random.Random(seed)
    old = [rng.choice("abc") for _ in range(rng.randint(0, 15))]
    new = [rng.choice("abc") for _ in range(rng.randint(0, 15))]

    ops = diff(old, new)

    assert edit_count(ops) == brute_force_distance(old, new)
    rebuilt = []
    for op in ops:
        if op.tag == "keep":
            assert old[op.old_start : op.old_end] == new[op.new_start : op.new_end]
        rebuilt.extend(new[op.new_start : op.new_end])
    assert rebuilt == new
