from collections import defaultdict

from notes.search import tokenize


class TagIndex:
    def __init__(self) -> None:
        self._by_tag: dict[str, set[str]] = defaultdict(set)

    def add(self, note) -> None:
        for tag in note.tags:
            self._by_tag[normalise_tag(tag)].add(note.slug)

    def slugs(self, tag: str) -> set[str]:
        return set(self._by_tag.get(normalise_tag(tag), set()))


def normalise_tag(tag: str) -> str:
    tokens = tokenize(tag.lstrip("#"))
    return "-".join(tokens)
