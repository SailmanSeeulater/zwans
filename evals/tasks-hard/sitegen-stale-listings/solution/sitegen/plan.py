"""Everything a build produces, each output with a signature of its inputs.

The builder only renders an output when its signature differs from the one recorded by
the last build, so a signature has to change whenever anything the output shows changes,
and should not change otherwise.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from sitegen import __version__
from sitegen.config import Config
from sitegen.content import Page, newest_first
from sitegen.feed import render_feed, render_sitemap
from sitegen.paginate import Pager, paginate
from sitegen.summaries import TagLink, summarize, tag_url
from sitegen.taxonomy import Tag, archive_years, collect_tags
from sitegen.templates import Engine


@dataclass
class Output:
    path: str  # relative to public/, with forward slashes
    signature: str
    render: Callable[[], str | bytes]


def signature(*parts: object) -> str:
    text = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def listing_key(posts: list[Page], max_words: int) -> list[dict[str, object]]:
    """What a listing of posts depends on: which posts it shows, in which order, and
    everything it shows about each of them (title, date, URL, tags, excerpt, ...)."""
    return [asdict(summarize(post, max_words)) for post in posts]


@dataclass
class TagInfo:
    name: str
    url: str
    count: int


@dataclass
class YearInfo:
    year: int
    summaries: list[object]


class SitePlan:
    def __init__(self, config: Config, engine: Engine, pages: list[Page]) -> None:
        self.config = config
        self.engine = engine
        self.pages = [page for page in pages if page.kind == "page"]
        self.posts = newest_first([page for page in pages if page.kind == "post"])
        self.tags = collect_tags(self.posts)
        # Anything that can change every page: settings, templates, sitegen itself.
        self.base = signature(__version__, config.fingerprint(), engine.fingerprint())

    def summaries(self, posts: list[Page]) -> list[object]:
        return [summarize(post, self.config.excerpt_words) for post in posts]

    def listing(self, posts: list[Page]) -> list[dict[str, object]]:
        return listing_key(posts, self.config.excerpt_words)

    def values(self, **values: object) -> dict[str, object]:
        return {"site": self.config, **values}

    # --- one output per kind ------------------------------------------------------

    def post(self, page: Page) -> Output:
        def render() -> str:
            tags = [TagLink(tag, tag_url(tag)) for tag in page.tags]
            values = self.values(title=page.title, page=page, content=page.html, tags=tags)
            return self.engine.render("post.html", values)

        return Output(page.output, signature(self.base, "post", page.fingerprint), render)

    def standalone(self, page: Page) -> Output:
        def render() -> str:
            values = self.values(title=page.title, page=page, content=page.html)
            return self.engine.render("page.html", values)

        return Output(page.output, signature(self.base, "page", page.fingerprint), render)

    def home(self, pager: Pager[Page]) -> Output:
        def render() -> str:
            title = "" if pager.number == 1 else f"Page {pager.number}"
            values = self.values(
                title=title, heading="", summaries=self.summaries(pager.items), pager=pager
            )
            return self.engine.render("list.html", values)

        key = signature(self.base, "home", pager.number, pager.count, self.listing(pager.items))
        return Output(pager.output, key, render)

    def tag(self, tag: Tag) -> Output:
        pager = paginate(tag.posts, max(1, len(tag.posts)), tag.url)[0]

        def render() -> str:
            heading = f"Posts tagged “{tag.name}”"
            values = self.values(
                title=tag.name, heading=heading, summaries=self.summaries(tag.posts), pager=pager
            )
            return self.engine.render("list.html", values)

        return Output(
            tag.output, signature(self.base, "tag", tag.name, self.listing(tag.posts)), render
        )

    def tag_index(self) -> Output:
        infos = [TagInfo(tag.name, tag.url, len(tag.posts)) for tag in self.tags]

        def render() -> str:
            return self.engine.render("tags.html", self.values(title="Tags", tags=infos))

        key = signature(self.base, "tags", [(i.name, i.url, i.count) for i in infos])
        return Output("tags/index.html", key, render)

    def archive(self) -> Output:
        def render() -> str:
            years = [YearInfo(y.year, self.summaries(y.posts)) for y in archive_years(self.posts)]
            return self.engine.render("archive.html", self.values(title="Archive", years=years))

        return Output(
            "archive/index.html", signature(self.base, "archive", self.listing(self.posts)), render
        )

    def feed(self) -> Output:
        newest = self.posts[: self.config.feed_size]

        def render() -> str:
            return render_feed(self.config, self.summaries(newest))  # type: ignore[arg-type]

        return Output("feed.xml", signature(self.base, "feed", self.listing(newest)), render)

    def sitemap(self, urls: list[str]) -> Output:
        def render() -> str:
            return render_sitemap(self.config, urls)

        return Output("sitemap.xml", signature(self.base, "sitemap", urls), render)

    # --- the whole site -----------------------------------------------------------

    def outputs(self) -> list[Output]:
        outputs: list[Output] = []
        outputs += [self.home(pager) for pager in paginate(self.posts, self.config.posts_per_page)]
        outputs += [self.post(post) for post in self.posts]
        outputs += [self.standalone(page) for page in self.pages]
        outputs += [self.tag(tag) for tag in self.tags]
        outputs.append(self.tag_index())
        outputs.append(self.archive())
        outputs.append(self.feed())
        pages = [output.path for output in outputs if output.path.endswith("index.html")]
        urls = sorted(path.removesuffix("index.html") for path in pages)
        outputs.append(self.sitemap(urls))
        return outputs


def static_outputs(static_dir: Path) -> list[Output]:
    """Files under static/ are copied to public/static/ unchanged."""
    outputs: list[Output] = []
    if not static_dir.is_dir():
        return outputs
    for source in sorted(static_dir.rglob("*")):
        if not source.is_file() or source.name.startswith("."):
            continue
        data = source.read_bytes()
        path = "static/" + source.relative_to(static_dir).as_posix()
        outputs.append(Output(path, hashlib.sha256(data).hexdigest()[:20], lambda data=data: data))
    return outputs
