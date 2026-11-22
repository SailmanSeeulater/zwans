"""The Memory tool: short notes about a project that later sessions start with.

Each session begins knowing nothing the last one learned: how the tests are run, which
folder is generated, what the user prefers. A note kept here goes into the system prompt of
every later session in the same folder.

The notes live in Zwans's home, one file per workspace, not in the project. Because they
steer later sessions, writing one is judged like changing a file: it asks in `ask` mode, and
after untrusted content has been read it follows the rule for writes, so a web page can't
quietly leave instructions for next time.
"""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_NOTES = 40
MAX_NOTE_CHARS = 400


def notes_file(home: Path, workspace: Path) -> Path:
    workspace = workspace.resolve()
    digest = hashlib.sha256(str(workspace).encode()).hexdigest()[:16]
    return home / "memory" / f"{workspace.name}-{digest}.md"


def read_notes(home: Path, workspace: Path) -> list[str]:
    """The notes kept for a workspace, oldest first."""
    try:
        text = notes_file(home, workspace).read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ")]


class MemoryInput(BaseModel):
    action: Literal["add", "remove"] = Field(
        description="add keeps a new note; remove deletes the one note that contains `text`."
    )
    text: str = Field(
        min_length=1,
        description="For add: the note, one sentence that will make sense on its own in a "
        "later session. For remove: enough of a note's words to pick it out.",
    )


class MemoryTool:
    name = "Memory"
    description = (
        "Keep a short note about this project for later sessions, which start with all the "
        "notes in front of them. Add one when you learn something that would have saved "
        "time: how the tests are run, what a folder is for, a preference the user stated. "
        "Don't note what the code or its README already says, or anything about this task "
        "alone. Remove a note that has stopped being true."
    )
    input_model = MemoryInput
    read_only = False

    def __init__(self, home: Path, workspace: Path) -> None:
        self.file = notes_file(home, workspace)
        self.home, self.workspace = home, workspace

    async def run(self, args: MemoryInput, ctx: ToolContext) -> ToolOutput:
        notes = read_notes(self.home, self.workspace)
        text = " ".join(args.text.split())
        if args.action == "add":
            if len(text) > MAX_NOTE_CHARS:
                raise ToolError(f"Keep a note under {MAX_NOTE_CHARS} characters: one sentence.")
            if text in notes:
                return ToolOutput(content=f"That note is already kept.\n\n{_listed(notes)}")
            if len(notes) >= MAX_NOTES:
                raise ToolError(
                    f"There are already {MAX_NOTES} notes. Remove one that's no longer true "
                    f"before adding another.\n\n{_listed(notes)}"
                )
            notes.append(text)
            done = "Kept."
        else:
            matching = [note for note in notes if text.lower() in note.lower()]
            if len(matching) != 1:
                found = "No note contains" if not matching else f"{len(matching)} notes contain"
                raise ToolError(f"{found} {text!r}, so nothing was removed.\n\n{_listed(notes)}")
            notes.remove(matching[0])
            done = "Removed."
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text("".join(f"- {note}\n" for note in notes), "utf-8")
        return ToolOutput(content=f"{done}\n\n{_listed(notes)}")


def _listed(notes: list[str]) -> str:
    if not notes:
        return "There are no notes for this project now."
    return "The notes for this project:\n" + "\n".join(f"- {note}" for note in notes)
