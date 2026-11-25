"""Turning text into search terms.

Terms are lower-cased words with very common words dropped and a light suffix strip, so
"linking", "linked" and "links" all find "link". The same function runs on pages and on
queries, which is all that matters for matching.
"""

import re
import unicodedata

STOPWORDS = frozenset(
    """
    a an and are as at be but by for from has have he her his i if in into is it its
    me my no not of on or our she so than that the their them then there these they this
    to too us was we were what when where which who will with you your
    """.split()
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalise(word: str) -> str:
    folded = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    """The search terms of a text, in order, repeats included."""
    out: list[str] = []
    for match in _WORD.finditer(text):
        word = normalise(match.group(0))
        if not keep_stopwords and word in STOPWORDS:
            continue
        out.append(stem(word))
    return out


def term_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for term in tokens(text):
        counts[term] = counts.get(term, 0) + 1
    return counts
