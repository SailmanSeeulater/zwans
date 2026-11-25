"""Turning text into search tokens: lower case, accents folded, split on anything that
isn't a letter or digit, a few filler words dropped, and a crude plural strip so "mugs"
finds "mug"."""

import re
import unicodedata

STOPWORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"})

_SPLIT = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def stem(token: str) -> str:
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and token[-3] in "sxz":
        return token[:-2]
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _SPLIT.split(fold(text)):
        if raw and raw not in STOPWORDS:
            tokens.append(stem(raw))
    return tokens


def code_tokens(code: str) -> list[str]:
    """A SKU or barcode is searchable whole and by its parts: "MUG-01-BL" gives
    "mug-01-bl", "mug", "01" and "bl"."""
    whole = code.strip().lower()
    parts = [p for p in re.split(r"[-_.]", whole) if p]
    return [whole, *parts]
