"""Short extracts of a page around the words a search matched."""

import re

from .tokenize import normalise, stem

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def snippet(text: str, terms: list[str], width: int = 120) -> str:
    """About ``width`` characters of ``text`` around the first matched term."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    wanted = set(terms)
    start = 0
    for match in _WORD.finditer(flat):
        if stem(normalise(match.group(0))) in wanted:
            start = max(0, match.start() - width // 3)
            break
    if start:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < start + 20 else start
    end = start + width
    piece = flat[start:end]
    if end < len(flat) and " " in piece:
        piece = piece[: piece.rindex(" ")]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + len(piece) < len(flat) else ""
    return prefix + piece + suffix
