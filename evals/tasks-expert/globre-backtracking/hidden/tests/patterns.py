"""Random patterns in the README's language, with their size, and texts to try them on.

Each generator returns (pattern, size, sample): `size` is the README's size of the pattern
(its character items, counting each copy a repeat makes) and `sample` makes a string the
pattern can match (anchors aside), so that random texts hit matches often.
"""

import random
from collections.abc import Callable

Sampler = Callable[[random.Random], str]
LETTERS = "abc"
EXTRA = "x0-./_ "
MAX_TEXT = 12


def node(rng: random.Random, depth: int = 0) -> tuple[str, int, bool, Sampler]:
    """An alternation: (text, size, can match empty, sampler)."""
    count = 1 if depth >= 2 or rng.random() < 0.6 else rng.randint(2, 3)
    options = [sequence(rng, depth) for _ in range(count)]
    text = "|".join(o[0] for o in options)
    size = sum(o[1] for o in options)
    empty = any(o[2] for o in options)

    def sample(r: random.Random) -> str:
        return r.choice(options)[3](r)

    return text, size, empty, sample


def sequence(rng: random.Random, depth: int) -> tuple[str, int, bool, Sampler]:
    items = []
    for _ in range(rng.choice([0, 1, 1, 2, 2, 3, 4]) if depth else rng.randint(1, 4)):
        roll = rng.random()
        if roll < 0.04:
            items.append(("^", 0, True, lambda r: ""))
        elif roll < 0.08:
            items.append(("$", 0, True, lambda r: ""))
        else:
            items.append(quantified(rng, depth))
    text = "".join(i[0] for i in items)
    size = sum(i[1] for i in items)
    empty = all(i[2] for i in items)

    def sample(r: random.Random) -> str:
        return "".join(i[3](r) for i in items)

    return text, size, empty, sample


def quantified(rng: random.Random, depth: int) -> tuple[str, int, bool, Sampler]:
    text, size, empty, sample = atom(rng, depth)
    if empty or rng.random() < 0.6:
        return text, size, empty, sample
    roll = rng.random()
    if roll < 0.25:
        low, high, written = 0, None, "*"
    elif roll < 0.45:
        low, high, written = 1, None, "+"
    elif roll < 0.6:
        low, high, written = 0, 1, "?"
    elif roll < 0.72:
        low = rng.randint(0, 3)
        high, written = low, f"{{{low}}}"
    elif roll < 0.84:
        low = rng.randint(0, 2)
        high, written = None, f"{{{low},}}"
    else:
        low = rng.randint(0, 2)
        high = low + rng.randint(0, 2)
        written = f"{{{low},{high}}}"
    copies = high if high is not None else low + 1

    def repeated(r: random.Random) -> str:
        times = r.randint(low, high if high is not None else low + 3)
        return "".join(sample(r) for _ in range(times))

    return text + written, size * copies, low == 0, repeated


CLASSES = [
    ("[ab]", "ab"), ("[^a]", "bcx0-. "), ("[a-c]", "abc"), ("[^b-c0]", "ax-./_ "),
    ("[a\\-]", "a-"), ("[-c]", "-c"), ("[b-]", "b-"), ("[\\d.]", "0."), ("[^\\w]", "-./ "),
    ("\\d", "0"), ("\\w", "abcx0_"), ("[.]", "."), ("[x-x]", "x"),
]


def atom(rng: random.Random, depth: int) -> tuple[str, int, bool, Sampler]:
    roll = rng.random()
    if roll < 0.5 or depth >= 3:
        ch = rng.choice(LETTERS) if rng.random() < 0.85 else rng.choice("x0-/_ ")
        return ch, 1, False, lambda r: ch
    if roll < 0.58:
        escaped = rng.choice([".", "*", "+", "(", ")", "|", "-", "/"])
        return "\\" + escaped, 1, False, lambda r: escaped
    if roll < 0.66:
        return ".", 1, False, lambda r: r.choice(LETTERS + EXTRA)
    if roll < 0.78:
        written, members = rng.choice(CLASSES)
        return written, 1, False, lambda r: r.choice(members)
    text, size, empty, sample = node(rng, depth + 1)
    return f"({text})", size, empty, sample


def pattern(rng: random.Random) -> tuple[str, int, Sampler]:
    text, size, _, sample = node(rng)
    return text, size, sample


def texts(rng: random.Random, sample: Sampler, count: int) -> list[str]:
    out = []
    for _ in range(count):
        roll = rng.random()
        if roll < 0.35:
            out.append(sample(rng))
        elif roll < 0.7:
            noise = lambda: "".join(rng.choice(LETTERS + "x") for _ in range(rng.randint(0, 3)))
            out.append(noise() + sample(rng) + noise())
        else:
            out.append("".join(rng.choice(LETTERS + EXTRA) for _ in range(rng.randint(0, 10))))
        if len(out[-1]) > MAX_TEXT:  # re itself backtracks, so keep texts short
            start = rng.randrange(len(out[-1]) - MAX_TEXT + 1)
            out[-1] = out[-1][start : start + MAX_TEXT]
    return out
