"""The search query language.

``kettle descale``        pages with both words (in any field)
``"hard water"``          the exact phrase, in the page's text
``-limescale``            pages without the word
``tag:kitchen``           pages tagged ``kitchen`` (``-tag:kitchen`` for the opposite)
``title:kettle``          the word must be in the title
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ..errors import QueryError
from ..tags import normalise_tag
from .tokenize import tokens


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    excluded_phrases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    excluded_tags: list[str] = field(default_factory=list)
    title_terms: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.terms or self.phrases or self.tags or self.title_terms)

    def positive_terms(self) -> list[str]:
        """Terms a match must contain somewhere, phrases broken into words."""
        out = list(self.terms) + list(self.title_terms)
        for phrase in self.phrases:
            out.extend(tokens(phrase))
        return out


def _split(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError as error:
        raise QueryError(f"can't read the query: {error}") from None


def parse_query(text: str) -> Query:
    query = Query()
    raw = text.strip()
    if not raw:
        return query
    # shlex drops the quotes, so remember which words were quoted phrases first
    quoted = {part.strip('"') for part in _quoted_parts(raw)}
    for part in _split(raw):
        negative = part.startswith("-") and len(part) > 1
        word = part[1:] if negative else part
        lowered = word.lower()
        if lowered.startswith("tag:"):
            tag = normalise_tag(word[4:])
            if not tag:
                raise QueryError("tag: needs a tag name")
            (query.excluded_tags if negative else query.tags).append(tag)
        elif lowered.startswith("title:"):
            if negative:
                raise QueryError("-title: is not supported")
            query.title_terms.extend(tokens(word[6:]))
        elif word in quoted and " " in word:
            (query.excluded_phrases if negative else query.phrases).append(word)
        else:
            found = tokens(word)
            (query.excluded if negative else query.terms).extend(found)
    return query


def _quoted_parts(text: str) -> list[str]:
    parts: list[str] = []
    inside = False
    current: list[str] = []
    for char in text:
        if char == '"':
            if inside:
                parts.append("".join(current))
                current = []
            inside = not inside
        elif inside:
            current.append(char)
    return parts
