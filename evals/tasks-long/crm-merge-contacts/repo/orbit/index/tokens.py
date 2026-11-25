"""Turning text into search tokens."""

import re

from orbit.text import fold

SPLIT = re.compile(r"[^0-9a-z]+")

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or the to was were will with".split()
)


def tokens(text: str) -> list[str]:
    """Folded words of `text`, without stop words and one-letter words (digits stay)."""
    words = SPLIT.split(fold(text))
    return [w for w in words if w and w not in STOPWORDS and (len(w) > 1 or w.isdigit())]


def phone_tokens(number: str) -> list[str]:
    digits = "".join(ch for ch in number if ch.isdigit())
    parts = tokens(number)
    return [*parts, digits] if digits and digits not in parts else parts
