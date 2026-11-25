"""An inverted index over pages, small enough to keep in memory and save as JSON.

Each document is one page, keyed by page id. The index keeps, per document, its title,
tags and plain text (for phrase checks and snippets), and per term the documents that
contain it with a weight: title words count three times, body words once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .query import Query
from .snippets import snippet
from .tokenize import normalise, term_counts, tokens

INDEX_VERSION = 1
TITLE_WEIGHT = 3


@dataclass
class Document:
    title: str
    tags: list[str]
    text: str
    length: int

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "tags": self.tags, "text": self.text, "length": self.length}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls(data["title"], list(data.get("tags", [])), data.get("text", ""), data["length"])


def _joined(text: str) -> str:
    """Terms separated by single spaces and padded, so phrases match whole words only."""
    return " " + " ".join(tokens(text, keep_stopwords=True)) + " "


class SearchIndex:
    def __init__(self) -> None:
        self.docs: dict[str, Document] = {}
        self.postings: dict[str, dict[str, int]] = {}
        self.generation = 0

    def __len__(self) -> int:
        return len(self.docs)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self.docs

    def add(self, doc_id: str, title: str, text: str, tags: list[str]) -> None:
        """Index a page, replacing whatever was indexed for it before."""
        self.remove(doc_id)
        weights: dict[str, int] = {}
        for term, count in term_counts(title).items():
            weights[term] = weights.get(term, 0) + TITLE_WEIGHT * count
        for term, count in term_counts(text).items():
            weights[term] = weights.get(term, 0) + count
        for term, weight in weights.items():
            self.postings.setdefault(term, {})[doc_id] = weight
        self.docs[doc_id] = Document(title, sorted(tags), text, sum(weights.values()))

    def remove(self, doc_id: str) -> None:
        if doc_id not in self.docs:
            return
        del self.docs[doc_id]
        empty: list[str] = []
        for term, entries in self.postings.items():
            if entries.pop(doc_id, None) is not None and not entries:
                empty.append(term)
        for term in empty:
            del self.postings[term]

    def retitle(self, doc_id: str, title: str) -> None:
        doc = self.docs.get(doc_id)
        if doc is not None:
            self.add(doc_id, title, doc.text, doc.tags)

    def clear(self) -> None:
        self.docs.clear()
        self.postings.clear()

    # -- querying --------------------------------------------------------------------

    def _idf(self, term: str) -> float:
        found = len(self.postings.get(term, {}))
        return math.log(1 + len(self.docs) / (1 + found))

    def _candidates(self, query: Query) -> set[str]:
        required = query.positive_terms()
        if required:
            sets = [set(self.postings.get(term, {})) for term in required]
            found = set.intersection(*sets)
        else:
            found = set(self.docs)
        for tag in query.tags:
            found = {d for d in found if tag in self.docs[d].tags}
        return found

    def _passes(self, doc_id: str, query: Query) -> bool:
        doc = self.docs[doc_id]
        title_terms = set(tokens(doc.title))
        if any(term not in title_terms for term in query.title_terms):
            return False
        if any(doc_id in self.postings.get(term, {}) for term in query.excluded):
            return False
        if any(tag in doc.tags for tag in query.excluded_tags):
            return False
        fields = [_joined(doc.title), _joined(doc.text)]
        for phrase in query.phrases:
            if not any(_joined(phrase) in field for field in fields):
                return False
        for phrase in query.excluded_phrases:
            if any(_joined(phrase) in field for field in fields):
                return False
        return True

    def search(self, query: Query, limit: int = 20) -> list[tuple[str, float, str]]:
        """(doc id, score, snippet), best first; ties go to the title's alphabetical order."""
        if query.is_empty:
            return []
        scored: list[tuple[float, str]] = []
        for doc_id in self._candidates(query):
            if not self._passes(doc_id, query):
                continue
            doc = self.docs[doc_id]
            score = 0.0
            for term in query.positive_terms():
                weight = self.postings.get(term, {}).get(doc_id, 0)
                score += weight * self._idf(term)
            score = score / math.sqrt(max(doc.length, 1)) if score else 1.0
            scored.append((round(score, 6), doc_id))
        scored.sort(key=lambda item: (-item[0], normalise(self.docs[item[1]].title)))
        results = []
        for score, doc_id in scored[:limit]:
            doc = self.docs[doc_id]
            results.append((doc_id, score, snippet(doc.text, query.positive_terms())))
        return results

    # -- persistence -----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INDEX_VERSION,
            "generation": self.generation,
            "docs": {doc_id: doc.to_dict() for doc_id, doc in sorted(self.docs.items())},
            "postings": {term: dict(sorted(e.items())) for term, e in sorted(self.postings.items())},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchIndex | None:
        """The saved index, or None when it was written by another index version."""
        if data.get("version") != INDEX_VERSION:
            return None
        index = cls()
        index.generation = int(data.get("generation", 0))
        index.docs = {k: Document.from_dict(v) for k, v in data.get("docs", {}).items()}
        index.postings = {k: dict(v) for k, v in data.get("postings", {}).items()}
        return index
