"""Loads ZWANS.md files: standing instructions from the user and from the project."""

from pathlib import Path

FILE_NAME = "ZWANS.md"


def load_instructions(workspace: Path, home: Path) -> list[tuple[Path, str]]:
    """Return (path, text) for each ZWANS.md found: the user's first, then the project's."""
    found: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path in (home / FILE_NAME, workspace / FILE_NAME):
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        text = resolved.read_text(encoding="utf-8-sig").strip()  # -sig: Notepad's BOM
        if text:
            found.append((resolved, text))
    return found
