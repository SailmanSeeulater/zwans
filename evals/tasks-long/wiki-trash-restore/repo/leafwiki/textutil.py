"""Small text helpers shared across the package: titles, slugs, word counts, excerpts."""

import re
import unicodedata

from .errors import InvalidTitle

MAX_TITLE = 120
_FORBIDDEN = set("[]|#<>{}\\/")
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def clean_title(title: str) -> str:
    """Normalise a page title (trim, collapse spaces) and check it is allowed."""
    if not isinstance(title, str):
        raise InvalidTitle("a title must be text")
    title = _SPACES.sub(" ", unicodedata.normalize("NFC", title)).strip()
    if not title:
        raise InvalidTitle("a title can't be empty")
    if len(title) > MAX_TITLE:
        raise InvalidTitle(f"a title can be at most {MAX_TITLE} characters")
    bad = sorted(set(title) & _FORBIDDEN)
    if bad:
        raise InvalidTitle(f"a title can't contain {' '.join(bad)}")
    if title.startswith("."):
        raise InvalidTitle("a title can't start with a dot")
    return title


def slugify(title: str) -> str:
    """The URL- and file-safe key of a title. Two titles with the same slug are the same page.

    >>> slugify("Front Page")
    'front-page'
    >>> slugify("  Café  au lait ")
    'café-au-lait'
    """
    text = unicodedata.normalize("NFC", title).casefold().strip()
    out: list[str] = []
    for char in text:
        if char.isalnum() or char in "-_.":
            out.append(char)
        elif char.isspace() or char in "'’,:;!?()&+":
            out.append("-")
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-")
    return slug or "page"


def same_title(a: str, b: str) -> bool:
    return slugify(a) == slugify(b)


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def word_count(text: str) -> int:
    return len(words(text))


def excerpt(text: str, length: int = 160) -> str:
    """The first ``length`` characters of plain text, cut at a word boundary."""
    text = _SPACES.sub(" ", text).strip()
    if len(text) <= length:
        return text
    cut = text[:length]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(",.;:") + "…"


def sort_key(title: str) -> tuple[str, str]:
    """Titles sort case-insensitively, ties broken by the exact text."""
    return (title.casefold(), title)


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"
