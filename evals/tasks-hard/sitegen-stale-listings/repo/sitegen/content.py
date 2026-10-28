"""Loading posts and pages from the content folder."""

import hashlib
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from sitegen import frontmatter, markup
from sitegen.slugify import slugify


class ContentError(Exception):
    pass


class Page:
    """One content file: a post (under content/posts/) or a stand-alone page.

    A page is identified by its source file, so two Page objects loaded from the same
    file are equal and hash the same. The taxonomy and the archive put pages in sets
    and dicts keyed by page.
    """

    def __init__(self, source: Path, relative: PurePosixPath, text: str) -> None:
        self.source = source
        self.relative = relative
        self.text = text
        try:
            self.meta, self.body = frontmatter.parse(text)
        except frontmatter.FrontMatterError as exc:
            raise ContentError(f"{relative}: {exc}") from exc
        self.kind = "post" if relative.parts[0] == "posts" else "page"
        self._check()

    def _check(self) -> None:
        if not isinstance(self.meta.get("title"), str) or not self.meta["title"]:
            raise ContentError(f"{self.relative}: needs a title")
        if self.kind == "post" and not isinstance(self.meta.get("date"), (date, datetime)):
            raise ContentError(f"{self.relative}: a post needs a date (YYYY-MM-DD)")
        tags = self.meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ContentError(f"{self.relative}: tags must be a list of words")
        self.meta["tags"] = tags

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Page) and self.source == other.source

    def __hash__(self) -> int:
        return hash(self.source)

    def __repr__(self) -> str:
        return f"Page({self.relative.as_posix()!r})"

    @property
    def title(self) -> str:
        return str(self.meta["title"])

    @property
    def date(self) -> datetime:
        value = self.meta.get("date")
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        return datetime(1970, 1, 1)

    @property
    def tags(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for tag in self.meta["tags"]:  # type: ignore[union-attr]
            seen.setdefault(tag.strip().lower(), None)
        return tuple(tag for tag in seen if tag)

    @property
    def draft(self) -> bool:
        return self.meta.get("draft") is True

    @property
    def summary(self) -> str | None:
        value = self.meta.get("summary")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def slug(self) -> str:
        given = self.meta.get("slug")
        if isinstance(given, str) and given.strip():
            return slugify(given)
        if self.kind == "page":
            return slugify(self.relative.stem)
        return slugify(self.title)

    @property
    def url(self) -> str:
        if self.kind == "post":
            return f"posts/{self.slug}/"
        return f"{self.slug}/"

    @property
    def output(self) -> str:
        return self.url + "index.html"

    @property
    def html(self) -> str:
        return markup.render(self.body)

    @property
    def fingerprint(self) -> str:
        """Changes whenever anything in the source file changes."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def load_content(content_dir: Path, *, drafts: bool = False) -> list[Page]:
    """Every page under content_dir, in path order. Drafts only if asked for."""
    pages: list[Page] = []
    if not content_dir.is_dir():
        return pages
    for source in sorted(content_dir.rglob("*.md")):
        relative = PurePosixPath(source.relative_to(content_dir).as_posix())
        if any(part.startswith((".", "_")) for part in relative.parts):
            continue
        page = Page(source, relative, source.read_text(encoding="utf-8"))
        if page.draft and not drafts:
            continue
        pages.append(page)
    _check_unique_urls(pages)
    return pages


def _check_unique_urls(pages: list[Page]) -> None:
    seen: dict[str, Page] = {}
    for page in pages:
        if page.url in seen:
            other = seen[page.url]
            raise ContentError(
                f"{page.relative} and {other.relative} would both be published at /{page.url}"
            )
        seen[page.url] = page


def newest_first(posts: list[Page]) -> list[Page]:
    """Posts sorted newest first; posts on the same date by title."""
    by_title = sorted(posts, key=lambda p: p.title.lower())
    return sorted(by_title, key=lambda p: p.date, reverse=True)
