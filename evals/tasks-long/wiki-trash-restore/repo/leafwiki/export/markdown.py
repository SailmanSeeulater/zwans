"""Export pages as Markdown files with a small front matter, one file per page.

The files can be read back with :func:`leafwiki.importer.import_folder`, which makes this
the simplest way to move pages between wikis.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Page
    from ..wiki import Wiki


def front_matter(page: Page) -> str:
    lines = ["---", f"title: {page.title}"]
    if page.tags:
        lines.append(f"tags: {', '.join(page.tags)}")
    lines.append(f"updated: {page.updated_at}")
    if page.last_author:
        lines.append(f"author: {page.last_author}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def export_markdown(wiki: Wiki, out_dir: str | Path) -> list[str]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for page in wiki.pages():
        name = f"{page.slug}.md"
        text = front_matter(page) + page.body.rstrip("\n") + "\n"
        (root / name).write_text(text, encoding="utf-8")
        written.append(name)
    return written
