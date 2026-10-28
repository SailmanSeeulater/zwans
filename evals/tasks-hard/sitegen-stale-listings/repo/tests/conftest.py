from pathlib import Path

import pytest
from sitegen.builder import Builder

SITE_TOML = """title = "Field Notes"
base_url = "https://notes.example.org/"
author = "Robin"
posts_per_page = 3
feed_size = 4
"""

POSTS = {
    "first-steps": ("First steps", "2025-11-02", ["notes"]),
    "ownership": ("Ownership, explained slowly", "2025-12-14", ["rust"]),
    "generators": ("Generators all the way down", "2026-01-09", ["python"]),
    "borrowck": ("Fighting the borrow checker", "2026-01-30", ["rust", "notes"]),
    "asyncio-tour": ("A tour of asyncio", "2026-02-21", ["python", "web"]),
    "static-sites": ("Why static sites", "2026-03-08", ["web"]),
    "packaging": ("Packaging in 2026", "2026-03-27", ["python"]),
}


def post_text(title: str, day: str, tags: list[str], body: str | None = None, **extra: str) -> str:
    lines = ["---", f"title: {title}", f"date: {day}", f"tags: [{', '.join(tags)}]"]
    lines += [f"{key}: {value}" for key, value in extra.items()]
    lines.append("---")
    if body is None:
        body = (
            f"The opening paragraph of {title.lower()}.\n\n"
            "A second paragraph with *details* and `code`.\n\n"
            "## More\n\nA closing paragraph.\n"
        )
    return "\n".join(lines) + "\n" + body


class Site:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def post(
        self,
        name: str,
        title: str,
        day: str,
        tags: list[str],
        body: str | None = None,
        **extra: str,
    ) -> Path:
        return self.write(f"content/posts/{name}.md", post_text(title, day, tags, body, **extra))

    def source(self, name: str) -> str:
        return (self.root / f"content/posts/{name}.md").read_text(encoding="utf-8")

    def edit(self, name: str, old: str, new: str) -> None:
        text = self.source(name)
        assert old in text, f"{old!r} is not in {name}.md"
        self.write(f"content/posts/{name}.md", text.replace(old, new, 1))

    def output(self, relative: str) -> str:
        return (self.root / "public" / relative).read_text(encoding="utf-8")

    def exists(self, relative: str) -> bool:
        return (self.root / "public" / relative).is_file()

    def builder(self, **options: bool) -> Builder:
        return Builder(self.root, **options)


@pytest.fixture
def site(tmp_path: Path) -> Site:
    """A small blog with seven posts and an about page; not built yet."""
    site = Site(tmp_path / "blog")
    site.write("site.toml", SITE_TOML)
    site.write("content/about.md", "---\ntitle: About\n---\nHello, I'm Robin.\n")
    for name, (title, day, tags) in POSTS.items():
        site.post(name, title, day, tags)
    return site
