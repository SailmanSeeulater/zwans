"""Full-text search over product names and SKUs.

An in-memory inverted index: token -> keys of the documents containing it. It is not saved;
the database rebuilds it from the products table when it loads or rolls back.

A query matches a document when every query token is a prefix of one of its tokens, so
"blu mu" finds "Blue mug".
"""

import re
from collections import defaultdict
from collections.abc import Hashable, Iterable

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


class SearchIndex:
    def __init__(self) -> None:
        self._postings: defaultdict[str, set[Hashable]] = defaultdict(set)
        self._documents: dict[Hashable, set[str]] = {}

    def add(self, key: Hashable, text: str) -> None:
        """Index text under key, replacing whatever key had before."""
        self.remove(key)
        words = tokens(text)
        self._documents[key] = words
        for word in words:
            self._postings[word].add(key)

    def remove(self, key: Hashable) -> None:
        for word in self._documents.pop(key, set()):
            self._postings[word].discard(key)
            if not self._postings[word]:
                del self._postings[word]

    def rebuild(self, documents: Iterable[tuple[Hashable, str]]) -> None:
        self._postings.clear()
        self._documents.clear()
        for key, text in documents:
            self.add(key, text)

    def search(self, query: str) -> list[Hashable]:
        """Keys of every document matching all of the query's tokens, sorted."""
        wanted = tokens(query)
        if not wanted:
            return []
        result: set[Hashable] | None = None
        for prefix in wanted:
            matches: set[Hashable] = set()
            for word, keys in self._postings.items():
                if word.startswith(prefix):
                    matches |= keys
            result = matches if result is None else result & matches
            if not result:
                return []
        return sorted(result, key=repr)

    def __len__(self) -> int:
        return len(self._documents)
