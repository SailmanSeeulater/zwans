"""Loads standing instructions: from the user, and from the project.

The user's are in ~/.zwans/ZWANS.md. A project's can be in ZWANS.md, CLAUDE.md or AGENTS.md
at its root, so a repository set up for Claude Code or another agent works as it is. All
three are read when there are several, AGENTS.md first and ZWANS.md last, since a later
file wins where two disagree; a file that's a link to another, or says the same thing, is
read once.

A line that is only `@path/to/file.md` brings in that file, as Claude Code does: a CLAUDE.md
that says `@AGENTS.md` is AGENTS.md. Only files inside the folder are brought in, one level
deep.
"""

from pathlib import Path

FILE_NAME = "ZWANS.md"
PROJECT_FILES = ("AGENTS.md", "CLAUDE.md", FILE_NAME)  # in order: the last one wins


def load_instructions(workspace: Path, home: Path) -> list[tuple[Path, str]]:
    """Return (path, text) for each instruction file found: the user's first, then the
    project's."""
    found: list[tuple[Path, str]] = []
    seen_paths: set[Path] = set()
    seen_texts: set[str] = set()
    candidates = [home / FILE_NAME, *(workspace / name for name in PROJECT_FILES)]
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen_paths or not resolved.is_file():
            continue
        seen_paths.add(resolved)
        text = _expand_imports(_read(resolved), path.parent.resolve(), seen_paths)
        if text and text not in seen_texts:
            seen_texts.add(text)
            found.append((resolved, text))
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig").strip()  # -sig: Notepad's BOM
    except (OSError, UnicodeDecodeError):
        return ""


def _expand_imports(text: str, folder: Path, seen: set[Path]) -> str:
    """Replace each line that is only `@relative/path` with that file's text."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        target = (folder / stripped[1:]).resolve() if stripped.startswith("@") else None
        if target is None or " " in stripped or not target.is_relative_to(folder):
            lines.append(line)
        elif target.is_file() and target not in seen:
            seen.add(target)  # so AGENTS.md isn't read again on its own
            lines.append(_read(target))
        elif not target.is_file():
            lines.append(line)  # not a file: maybe a mention, so leave it as written
    return "\n".join(lines).strip()
