"""Importing a folder of text files as pages.

Each ``.md`` or ``.txt`` file becomes a page. The title comes from a front matter
``title:`` line, else from a first-line ``# Heading``, else from the file name
("kettle-care.md" becomes "Kettle care"). A front matter ``tags:`` line sets the tags.
Files whose page already exists update it, and unchanged ones are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import WikiError
from .textutil import clean_title

if TYPE_CHECKING:
    from .wiki import Wiki

SUFFIXES = (".md", ".txt")


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{len(self.created)} created",
            f"{len(self.updated)} updated",
            f"{len(self.unchanged)} unchanged",
        ]
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    body = text[end + 4 :]
    return fields, body.lstrip("\n")


def title_from_name(path: Path) -> str:
    words = path.stem.replace("_", " ").replace("-", " ").split()
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def read_page_file(path: Path) -> tuple[str, str, list[str]]:
    text = path.read_text("utf-8").replace("\r\n", "\n")
    fields, body = split_front_matter(text)
    title = fields.get("title", "")
    if not title:
        first, _, rest = body.partition("\n")
        if first.startswith("# "):
            title, body = first[2:].strip(), rest.lstrip("\n")
    tags = [t.strip() for t in fields.get("tags", "").split(",") if t.strip()]
    return clean_title(title or title_from_name(path)), body.rstrip("\n") + "\n", tags


def import_folder(wiki: Wiki, folder: str | Path, author: str = "import") -> ImportResult:
    result = ImportResult()
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        try:
            title, body, tags = read_page_file(path)
            if wiki.exists(title):
                before = wiki.page(title)
                after = wiki.edit_page(title, body, author, summary=f"Imported from {path.name}")
                if tags:
                    after = wiki.add_tags(title, tags, author)
                if after.current.number == before.current.number and after.tags == before.tags:
                    result.unchanged.append(after.title)
                else:
                    result.updated.append(after.title)
            else:
                page = wiki.create_page(
                    title, body, author, summary=f"Imported from {path.name}", tags=tags
                )
                result.created.append(page.title)
        except (WikiError, UnicodeDecodeError) as error:
            result.failed.append((path.name, str(error)))
    return result
