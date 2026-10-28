from notes.models import Note
from notes.util import slugify


def test_slugify() -> None:
    assert slugify("Crème brûlée, again!") == "creme-brulee-again"


def test_markdown() -> None:
    note = Note("Shopping", "eggs", {"home", "todo"})
    assert note.to_markdown() == "# Shopping\n\nTags: #home, #todo\n\neggs\n"
