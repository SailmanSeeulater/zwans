from pathlib import Path

from notes.render import render_index, render_note
from notes.storage import Store


def export_markdown(store: Store, target: Path) -> int:
    notes = store.all()
    target.mkdir(parents=True, exist_ok=True)
    for note in notes:
        (target / f"{note.slug}.md").write_text(render_note(note), encoding="utf-8")
    (target / "index.md").write_text(render_index(notes), encoding="utf-8")
    return len(notes)
