import re

from sitegen.cli import main
from sitegen.serve import Watcher

ALL_POSTS = {
    "posts/a-tour-of-asyncio/index.html",
    "posts/fighting-the-borrow-checker/index.html",
    "posts/first-steps/index.html",
    "posts/generators-all-the-way-down/index.html",
    "posts/ownership-explained-slowly/index.html",
    "posts/packaging-in-2026/index.html",
    "posts/why-static-sites/index.html",
}


def titles_in(html: str) -> list[str]:
    return re.findall(r'<h2><a href="[^"]+">([^<]+)</a></h2>', html)


def test_a_retitled_post_shows_its_new_title_on_every_listing(site) -> None:
    site.builder().build()
    site.edit("asyncio-tour", "title: A tour of asyncio", "title: Asyncio, a guided tour")

    report = site.builder().build()

    for listing in ("index.html", "tags/python/index.html", "tags/web/index.html"):
        html = site.output(listing)
        assert "Asyncio, a guided tour" in titles_in(html), listing
        assert "A tour of asyncio" not in html, listing
        assert 'href="/posts/asyncio-a-guided-tour/"' in html, listing
    assert "Asyncio, a guided tour" in site.output("archive/index.html")
    assert "A tour of asyncio" not in site.output("archive/index.html")
    assert "<title>Asyncio, a guided tour</title>" in site.output("feed.xml")
    assert "posts/a-tour-of-asyncio/index.html" in report.removed


def test_a_retitle_only_rewrites_the_listings_the_post_is_on(site) -> None:
    site.builder().build()
    site.edit("asyncio-tour", "title: A tour of asyncio", "title: Asyncio, a guided tour")

    written = set(site.builder().build().written)

    assert {
        "posts/asyncio-a-guided-tour/index.html",
        "index.html",
        "tags/python/index.html",
        "tags/web/index.html",
        "archive/index.html",
        "feed.xml",
    } <= written
    untouched = {
        "tags/rust/index.html",
        "tags/notes/index.html",
        "page/2/index.html",
        "page/3/index.html",
    }
    untouched |= ALL_POSTS - {"posts/a-tour-of-asyncio/index.html"}
    assert not written & untouched
    assert site.builder().build().written == []


def test_serve_picks_up_a_retitle(site) -> None:
    builder = site.builder()
    builder.build()
    watcher = Watcher(builder)

    site.edit(
        "borrowck",
        "title: Fighting the borrow checker",
        "title: Making peace with the borrow checker",
    )
    report = watcher.poll_once()

    assert report is not None
    page_two = site.output("page/2/index.html")
    assert titles_in(page_two)[0] == "Making peace with the borrow checker"
    assert "Fighting" not in page_two
    assert "Making peace with the borrow checker" in titles_in(site.output("tags/rust/index.html"))
    assert "Making peace with the borrow checker" in titles_in(site.output("tags/notes/index.html"))
    assert "Fighting" not in site.output("feed.xml")
    assert "tags/python/index.html" not in report.written
    assert watcher.poll_once() is None


def test_serve_follows_several_edits_in_a_row(site) -> None:
    builder = site.builder()
    builder.build()
    watcher = Watcher(builder)

    for title in ("Packaging in 2026, revisited", "Packaging, again", "Packaging in 2026"):
        site.write(
            "content/posts/packaging.md",
            site.source("packaging").replace(
                site.source("packaging").splitlines()[1], f"title: {title}"
            ),
        )
        assert watcher.poll_once() is not None
        assert titles_in(site.output("index.html"))[0] == title
        assert titles_in(site.output("tags/python/index.html"))[0] == title


def test_a_new_date_shows_on_listings_even_when_the_order_stays(site) -> None:
    assert main(["build", str(site.root), "--quiet"]) == 0
    site.edit("ownership", "date: 2025-12-14", "date: 2025-12-20")

    assert main(["build", str(site.root), "--quiet"]) == 0

    for listing in ("page/2/index.html", "tags/rust/index.html", "archive/index.html"):
        assert "20 Dec 2025" in site.output(listing), listing
        assert "14 Dec 2025" not in site.output(listing), listing


def test_an_edited_first_paragraph_updates_the_excerpts(site) -> None:
    site.builder().build()
    site.edit(
        "packaging",
        "The opening paragraph of packaging in 2026.",
        "Packaging has finally become boring, in a good way.",
    )

    site.builder().build()

    for listing in ("index.html", "tags/python/index.html"):
        assert "finally become boring" in site.output(listing), listing
        assert "opening paragraph of packaging" not in site.output(listing), listing
    assert "finally become boring" in site.output("feed.xml")


def test_a_new_summary_replaces_the_excerpt_on_listings(site) -> None:
    site.builder().build()
    site.edit("static-sites", "tags: [web]", "tags: [web]\nsummary: Fewer moving parts.")

    site.builder().build()

    for listing in ("index.html", "tags/web/index.html"):
        assert "Fewer moving parts." in site.output(listing), listing
        assert "opening paragraph of why static sites" not in site.output(listing), listing


def test_new_tags_show_on_listings_the_post_was_already_on(site) -> None:
    site.builder().build()
    site.edit("asyncio-tour", "tags: [python, web]", "tags: [python, web, async]")

    report = site.builder().build()

    assert "tags/async/index.html" in report.written
    for listing in ("index.html", "tags/python/index.html", "tags/web/index.html"):
        assert '<a href="/tags/async/">async</a>' in site.output(listing), listing


def test_a_longer_post_shows_its_new_reading_time(site) -> None:
    site.builder().build()
    assert "· 1 min" in site.output("index.html")
    site.edit("packaging", "A closing paragraph.", "A closing paragraph. " + "word " * 600)

    site.builder().build()

    home = site.output("index.html")
    assert home.count("· 3 min") == 1
    assert "· 3 min" in site.output("tags/python/index.html")
