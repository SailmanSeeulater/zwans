"""Skills: folders of instructions for particular kinds of task, loaded only when needed.

A skill is a folder with a SKILL.md, in ~/.zwans/skills/ or <workspace>/.zwans/skills/:

    ---
    name: release-notes
    description: Write release notes from the git log. Use when asked for a changelog.
    ---
    (the instructions)

Only the names and descriptions go in the system prompt. The model reads the rest with the
Skill tool when a task calls for it, so a dozen skills cost a few lines of context until one
is used. A skill's folder can hold other files (templates, scripts, references) that the
model loads the same way.
"""

from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "SKILL.md"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    folder: Path

    def instructions(self) -> str:
        return split_front_matter(self.read(FILE_NAME))[1].strip()

    def read(self, file: str) -> str:
        """A file from the skill's folder. Raises OSError for anything outside it."""
        path = (self.folder / file).resolve()
        if not path.is_relative_to(self.folder):
            raise PermissionError(f"{file} is outside the skill's folder")
        return path.read_text(encoding="utf-8-sig")

    def other_files(self) -> list[str]:
        files = (p for p in self.folder.rglob("*") if p.is_file() and p.name != FILE_NAME)
        return sorted(p.relative_to(self.folder).as_posix() for p in files)


def find_skills(folders: list[Path]) -> list[Skill]:
    """The skills in these folders, in order. A later folder's skill replaces an earlier one
    with the same name, so a project's skill wins over the user's."""
    found: dict[str, Skill] = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for skill_file in sorted(folder.glob(f"*/{FILE_NAME}")):
            skill = _load(skill_file)
            if skill is not None:
                found[skill.name] = skill
    return list(found.values())


def skill_folders(workspace: Path, home: Path | None) -> list[Path]:
    folders = [home / "skills"] if home is not None else []
    return [*folders, workspace / ".zwans" / "skills"]


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Read simple `key: value` front matter between --- lines. Returns it and the rest."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return {}, text
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[key.strip()] = value
    return fields, "\n".join(lines[end + 1 :])


def _load(skill_file: Path) -> Skill | None:
    try:
        text = skill_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    fields, _ = split_front_matter(text)
    name = fields.get("name") or skill_file.parent.name
    description = fields.get("description", "").strip()
    if not description:
        return None  # the model would have no way to know when to use it
    return Skill(name=name, description=description, folder=skill_file.parent.resolve())
