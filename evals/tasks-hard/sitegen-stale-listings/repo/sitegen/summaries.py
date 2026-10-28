"""What listings show about a post: its title, date, tags and excerpt."""

from dataclasses import dataclass
from datetime import datetime
from functools import cache

from sitegen import markup
from sitegen.content import Page
from sitegen.slugify import slugify

WORDS_PER_MINUTE = 220


@dataclass(frozen=True)
class TagLink:
    name: str
    url: str


@dataclass(frozen=True)
class Summary:
    title: str
    url: str
    date: datetime
    tags: tuple[TagLink, ...]
    excerpt: str  # HTML
    reading_minutes: int


def tag_url(tag: str) -> str:
    return f"tags/{slugify(tag)}/"


def excerpt_html(page: Page, max_words: int) -> str:
    text = page.summary or markup.first_paragraph(page.body)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]) + " …"
    return markup.inline(text)


def reading_minutes(page: Page) -> int:
    words = len(markup.plain_text(page.body).split())
    return max(1, round(words / WORDS_PER_MINUTE))


# A post shows up on the home page, the archive, every one of its tag pages and the
# feed, and rendering the excerpt and counting words is the slow part, so summaries
# are worked out once per page.
@cache
def summarize(page: Page, max_words: int) -> Summary:
    return Summary(
        title=page.title,
        url=page.url,
        date=page.date,
        tags=tuple(TagLink(tag, tag_url(tag)) for tag in page.tags),
        excerpt=excerpt_html(page, max_words),
        reading_minutes=reading_minutes(page),
    )
