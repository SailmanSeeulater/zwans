"""Tags, and the year-by-year archive."""

from dataclasses import dataclass

from sitegen.content import Page, newest_first
from sitegen.slugify import slugify


@dataclass
class Tag:
    name: str
    posts: list[Page]

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def url(self) -> str:
        return f"tags/{self.slug}/"

    @property
    def output(self) -> str:
        return self.url + "index.html"


def collect_tags(posts: list[Page]) -> list[Tag]:
    """Every tag used by a post, alphabetically, each with its posts newest first.

    Tags that differ only in case or punctuation ("Web-Dev", "web dev") are one tag;
    it is named after the spelling its newest post uses.
    """
    by_slug: dict[str, set[Page]] = {}
    names: dict[str, str] = {}
    for post in newest_first(posts):
        for tag in post.tags:
            slug = slugify(tag)
            by_slug.setdefault(slug, set()).add(post)
            names.setdefault(slug, tag)
    return [Tag(names[slug], newest_first(list(by_slug[slug]))) for slug in sorted(by_slug)]


@dataclass
class Year:
    year: int
    posts: list[Page]


def archive_years(posts: list[Page]) -> list[Year]:
    """Posts grouped by year, newest year first, newest post first within a year."""
    years: dict[int, list[Page]] = {}
    for post in newest_first(posts):
        years.setdefault(post.date.year, []).append(post)
    return [Year(year, years[year]) for year in sorted(years, reverse=True)]
