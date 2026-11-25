"""The matcher against the README: the same answers as Python's re on random patterns
and texts, and never more than 2 * size * (n + 1) steps, on short texts, on long lines and
on patterns that make backtracking matchers blow up."""

import random
import re

import patterns
import pytest

import logq


class OverBudget(AssertionError):
    pass


class Budget:
    """A meter that stops the match as soon as it goes over the README's limit."""

    def __init__(self, size: int, text: str) -> None:
        self.limit = 2 * size * (len(text) + 1)
        self.steps = 0

    def step(self) -> None:
        self.steps += 1
        if self.steps > self.limit:
            raise OverBudget(f"more than {self.limit} steps")


def search(pattern: str, size: int, text: str) -> tuple[int, int] | None:
    compiled = logq.compile(pattern)
    assert compiled.size == size
    return compiled.search(text, Budget(size, text))


def fullmatch(pattern: str, size: int, text: str) -> bool:
    return logq.compile(pattern).fullmatch(text, Budget(size, text))


# -- random patterns: exactly what re does


@pytest.mark.parametrize("seed", range(150))
def test_random_patterns_match_like_re(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(12):
        pattern, size, sample = patterns.pattern(rng)
        compiled = logq.compile(pattern)
        assert compiled.size == size, f"{pattern!r} has size {size}, not {compiled.size}"
        rx = re.compile(pattern)
        for text in patterns.texts(rng, sample, 12):
            want = rx.search(text)
            got = compiled.search(text, Budget(size, text))
            assert got == (want.span() if want else None), (
                f"search({pattern!r}, {text!r}) gave {got}; re gives {want.span() if want else None}"
            )
            want_whole = rx.fullmatch(text) is not None
            got_whole = compiled.fullmatch(text, Budget(size, text))
            assert got_whole == want_whole, (
                f"fullmatch({pattern!r}, {text!r}) gave {got_whole}; re gives {want_whole}"
            )


# -- patterns that make backtracking blow up (re included: the answers are worked out by
#    hand here)

A = "a" * 3000


@pytest.mark.parametrize(
    ("pattern", "size", "text", "found", "whole"),
    [
        ("(a|aa)*b", 4, A, None, False),
        ("(a|aa)*b", 4, A + "b", (0, 3001), True),
        ("(a|aa)*b", 4, "c" + A + "c", None, False),
        ("(x+x+)+y", 9, "x" * 2000, None, False),
        ("(x+x+)+y", 9, "x" * 2000 + "y", (0, 2001), True),
        ("(a+)+b", 5, A + "c", None, False),
        ("^(\\w+ ?)+$", 6, "word " * 600 + "!", None, False),
        ("^(\\w+ ?)+$", 6, "word " * 600 + "end", (0, 3003), True),
        ("(.*a){8}", 16, "a" * 20 + "b" * 3000, (0, 20), False),
        ("(.*a){8}", 16, "a" * 20 + "b" * 3000 + "a", (0, 3021), True),
        ("(a|b|ab)*c", 5, "ab" * 1500, None, False),
        ("(a|b|ab)*c", 5, "ab" * 1500 + "c", (0, 3001), True),
        ("(a{1,3}){2,}b", 10, A, None, False),
        ("([ab]|a)*$", 2, "ab" * 1000 + "c", (2001, 2001), False),
    ],
)
def test_patterns_that_blow_up_backtracking(
    pattern: str, size: int, text: str, found: tuple[int, int] | None, whole: bool
) -> None:
    assert search(pattern, size, text) == found
    assert fullmatch(pattern, size, text) == whole


# -- long lines


def long_line(seed: int, length: int) -> str:
    rng = random.Random(seed)
    words = ["GET", "/api/v1/items", "user=ana", "status=200", "10.0.0.12", "[warn]", "ok",
             "latency=31ms", "-", "retry"]
    parts = []
    while sum(map(len, parts)) < length:
        parts.append(rng.choice(words))
    return " ".join(parts)


@pytest.mark.parametrize(
    ("pattern", "size"),
    [
        ("status=500", 10),
        ("^GET.*retry$", 9),
        ("(\\d+\\.){3}\\d+", 11),
        ("user=\\w+ .*latency=\\d+ms$", 21),
        ("\\[[^\\]]*\\]", 3),
        ("[a-z]+=[0-9]+ms", 7),
        ("x*-.*", 3),
    ],
)
def test_long_lines(pattern: str, size: int) -> None:
    text = long_line(len(pattern), 30000)
    rx = re.compile(pattern)

    want = rx.search(text)
    assert search(pattern, size, text) == (want.span() if want else None)
    assert fullmatch(pattern, size, text) == (rx.fullmatch(text) is not None)


def test_a_line_that_is_one_long_match() -> None:
    text = "[" + "x" * 100000 + "]"

    assert search("\\[x*\\]", 3, text) == (0, len(text))
    assert fullmatch("\\[(x|y)*\\]", 4, text)
    assert search("\\[[^\\]]*\\](z|$)", 4, text) == (0, len(text))


# -- the rest of the README


@pytest.mark.parametrize(
    "pattern",
    ["*a", "a**", "a+?", "a{2}*", "(a?)*", "(a|)+", "()*", "(^)?", "(b{0}){2}", "[]", "[z-a]",
     "a{3,2}", "\\n", "(ab", "a)", "a]", "a}", "[ab", "a{1001}"],
)
def test_patterns_outside_the_language_are_refused(pattern: str) -> None:
    with pytest.raises(logq.PatternError):
        logq.compile(pattern)


def test_the_meter_is_called_for_each_step() -> None:
    budget = Budget(2, "xxab")
    assert logq.compile("ab").search("xxab", budget) == (2, 4)
    assert 0 < budget.steps <= budget.limit
