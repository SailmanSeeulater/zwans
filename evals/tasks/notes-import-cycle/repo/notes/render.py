from notes.models import Note
from notes.util import slugify


def render_note(note: Note) -> str:
    lines = [f"# {note.title}", ""]
    if note.tags:
        lines.append("Tags: " + ", ".join(f"#{tag}" for tag in sorted(note.tags)))
        lines.append("")
    lines.append(note.body)
    return "\n".join(lines).rstrip() + "\n"


def render_index(notes: list[Note]) -> str:
    rows = [f"- [{note.title}]({slugify(note.title)}.md)" for note in notes]
    return "\n".join(["# Index", "", *rows]) + "\n"
