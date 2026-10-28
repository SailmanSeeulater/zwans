from notes.storage import Store
from notes.util import words

STOP_WORDS = {"a", "an", "and", "the", "of", "to", "in"}


def tokenize(text: str) -> list[str]:
    return [word for word in words(text) if word not in STOP_WORDS]


def search(store: Store, query: str) -> list[str]:
    """Slugs of notes containing every query word, best matches first."""
    wanted = set(tokenize(query))
    scored = []
    for note in store.all():
        found = tokenize(note.title + " " + note.body)
        if wanted <= set(found):
            scored.append((-sum(found.count(word) for word in wanted), note.slug))
    return [slug for _, slug in sorted(scored)]
