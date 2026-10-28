"""Notes live as `<slug>.txt` files: tags on the first line, body after a blank line."""

from pathlib import Path

from notes.models import Note
from notes.tags import TagIndex


class Store:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.tags = TagIndex()
        for note in self.all():
            self.tags.add(note)

    def put(self, note: Note) -> None:
        header = " ".join(sorted(note.tags))
        text = f"{note.title}\n{header}\n\n{note.body}\n"
        (self.folder / f"{note.slug}.txt").write_text(text, encoding="utf-8")
        self.tags.add(note)

    def all(self) -> list[Note]:
        notes = []
        for path in sorted(self.folder.glob("*.txt")):
            title, header, _, *body = path.read_text(encoding="utf-8").split("\n")
            notes.append(Note(title, "\n".join(body).rstrip("\n"), set(header.split())))
        return notes
