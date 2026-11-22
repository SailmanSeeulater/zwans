"""The Memory tool: short notes about a project that later sessions start with.

Each session begins knowing nothing the last one learned: how the tests are run, which
folder is generated, what the user prefers. A note kept here goes into the system prompt of
every later session in the same folder.

A note is a fact, not a procedure, and it comes with its evidence: what showed it true (a
command and what it printed, a file and line, the user's words) and the day it was last
seen to hold. A later session can then weigh a note by what backs it, check it again, and
drop it when what it sees says otherwise, instead of following a stale instruction.

The notes live in Zwans's home, one file per workspace, not in the project. Because they
steer later sessions, writing one is judged like changing a file: it asks in `ask` mode, and
after untrusted content has been read it follows the rule for writes, so a web page can't
quietly leave instructions for next time.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_NOTES = 40
MAX_NOTE_CHARS = 400
MAX_EVIDENCE_CHARS = 300
EVIDENCE = "  shown by: "  # the lines under a note, in its file
CHECKED = "  checked: "


@dataclass
class Note:
    text: str
    evidence: str = ""  # empty for a note kept before notes had evidence
    checked: str = ""  # the day it was last seen to hold, as 2026-11-22

    def render(self) -> str:
        """The note as a session sees it, its evidence alongside."""
        if not self.evidence:
            return f"{self.text} [no evidence kept]"
        when = f"; checked {self.checked}" if self.checked else ""
        return f"{self.text} [shown by: {self.evidence}{when}]"

    def lines(self) -> str:
        out = f"- {self.text}\n"
        if self.evidence:
            out += f"{EVIDENCE}{self.evidence}\n"
        if self.checked:
            out += f"{CHECKED}{self.checked}\n"
        return out


def notes_file(home: Path, workspace: Path) -> Path:
    workspace = workspace.resolve()
    digest = hashlib.sha256(str(workspace).encode()).hexdigest()[:16]
    return home / "memory" / f"{workspace.name}-{digest}.md"


def kept_notes(home: Path, workspace: Path) -> list[Note]:
    """The notes kept for a workspace, oldest first."""
    try:
        text = notes_file(home, workspace).read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    notes: list[Note] = []
    for line in text.splitlines():
        if line.startswith("- "):
            notes.append(Note(line[2:].strip()))
        elif notes and line.startswith(EVIDENCE):
            notes[-1].evidence = line.removeprefix(EVIDENCE).strip()
        elif notes and line.startswith(CHECKED):
            notes[-1].checked = line.removeprefix(CHECKED).strip()
    return notes


def read_notes(home: Path, workspace: Path) -> list[str]:
    """The notes kept for a workspace, as the system prompt lists them."""
    return [note.render() for note in kept_notes(home, workspace)]


class MemoryInput(BaseModel):
    action: Literal["add", "confirm", "remove"] = Field(
        description="add keeps a new note; confirm records fresh evidence for the one note "
        "that contains `text`, when you've seen it hold in a new way; remove deletes the "
        "one note that contains `text`, as when what you see contradicts it."
    )
    text: str = Field(
        min_length=1,
        description="For add: the note, one sentence stating a fact that will make sense on "
        "its own in a later session. For confirm and remove: enough of a note's words to "
        "pick it out.",
    )
    evidence: str | None = Field(
        default=None,
        description="For add and confirm: what showed it's true, specific enough to check "
        "again: a command and what it printed, a file and line, or the user's own words.",
    )


class MemoryTool:
    name = "Memory"
    description = (
        "Keep a short note about this project for later sessions, which start with all the "
        "notes in front of them. Add one when you learn something that would have saved "
        "time: how the tests are run, what a folder is for, a preference the user stated. "
        "A note states a fact, not a list of steps, and comes with its evidence: what you "
        "saw that shows it. Don't note what the code or its README already says, or anything "
        "about this task alone. Remove a note that what you see contradicts."
    )
    input_model = MemoryInput
    read_only = False

    def __init__(self, home: Path, workspace: Path, today: Callable[[], date] = date.today) -> None:
        self.file = notes_file(home, workspace)
        self.home, self.workspace = home, workspace
        self.today = today

    async def run(self, args: MemoryInput, ctx: ToolContext) -> ToolOutput:
        notes = kept_notes(self.home, self.workspace)
        text = " ".join(args.text.split())
        evidence = " ".join((args.evidence or "").split())
        if args.action in ("add", "confirm"):
            if not evidence:
                raise ToolError(
                    "Say what showed it's true, in `evidence`: a command and what it printed, "
                    "a file and line, or the user's words."
                )
            if len(evidence) > MAX_EVIDENCE_CHARS:
                raise ToolError(f"Keep the evidence under {MAX_EVIDENCE_CHARS} characters.")
        checked = self.today().isoformat()
        if args.action == "add":
            if len(text) > MAX_NOTE_CHARS:
                raise ToolError(f"Keep a note under {MAX_NOTE_CHARS} characters: one sentence.")
            if any(note.text == text for note in notes):
                return ToolOutput(
                    content=f"That note is already kept; confirm it to record new evidence."
                    f"\n\n{_listed(notes)}"
                )
            if len(notes) >= MAX_NOTES:
                raise ToolError(
                    f"There are already {MAX_NOTES} notes. Remove one that's no longer true "
                    f"before adding another.\n\n{_listed(notes)}"
                )
            notes.append(Note(text, evidence, checked))
            done = "Kept."
        else:
            note = _the_one(notes, text)
            if args.action == "confirm":
                note.evidence, note.checked = evidence, checked
                done = "Confirmed."
            else:
                notes.remove(note)
                done = "Removed."
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text("".join(note.lines() for note in notes), "utf-8")
        return ToolOutput(content=f"{done}\n\n{_listed(notes)}")


def _the_one(notes: list[Note], text: str) -> Note:
    matching = [note for note in notes if text.lower() in note.text.lower()]
    if len(matching) != 1:
        found = "No note contains" if not matching else f"{len(matching)} notes contain"
        raise ToolError(f"{found} {text!r}, so nothing was changed.\n\n{_listed(notes)}")
    return matching[0]


def _listed(notes: list[Note]) -> str:
    if not notes:
        return "There are no notes for this project now."
    return "The notes for this project:\n" + "\n".join(f"- {note.render()}" for note in notes)
