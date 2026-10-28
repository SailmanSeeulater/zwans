import re

import pytest
from sitegen.cli import main, new_post
from sitegen.content import ContentError


def titles_in(html: str) -> list[str]:
    return re.findall(r'<h2><a href="[^"]+">([^<]+)</a></h2>', html)


def test_a_full_build_writes_every_page(site) -> None:
    report = site.builder().build()

    assert sorted(report.written) == [
        "about/index.html",
        "archive/index.html",
        "feed.xml",
        "index.html",
        "page/2/index.html",
        "page/3/index.html",
        "posts/a-tour-of-asyncio/index.html",
        "posts/fighting-the-borrow-checker/index.html",
        "posts/first-steps/index.html",
        "posts/generators-all-the-way-down/index.html",
        "posts/ownership-explained-slowly/index.html",
        "posts/packaging-in-2026/index.html",
        "posts/why-static-sites/index.html",
        "sitemap.xml",
        "tags/index.html",
        "tags/notes/index.html",
        "tags/python/index.html",
        "tags/rust/index.html",
        "tags/web/index.html",
    ]
    assert report.unchanged == [] and report.removed == []


def test_home_pages_list_posts_newest_first(site) -> None:
    site.builder().build()

    assert titles_in(site.output("index.html")) == [
        "Packaging in 2026",
        "Why static sites",
        "A tour of asyncio",
    ]
    assert titles_in(site.output("page/3/index.html")) == ["First steps"]
    assert 'rel="next" href="/page/2/"' in site.output("index.html")
    assert 'rel="prev" href="/page/2/"' in site.output("page/3/index.html")


def test_listings_show_title_date_tags_and_excerpt(site) -> None:
    site.builder().build()
    home = site.output("index.html")

    assert "27 Mar 2026" in home
    assert '<a href="/tags/python/">python</a>' in home
    assert "The opening paragraph of packaging in 2026." in home
    assert "A closing paragraph." not in home


def test_tag_pages(site) -> None:
    site.builder().build()

    assert titles_in(site.output("tags/python/index.html")) == [
        "Packaging in 2026",
        "A tour of asyncio",
        "Generators all the way down",
    ]
    assert "rust</a> (2 posts)" in site.output("tags/index.html")


def test_archive_groups_by_year(site) -> None:
    site.builder().build()
    archive = site.output("archive/index.html")

    assert archive.index("<h2>2026</h2>") < archive.index("<h2>2025</h2>")
    assert archive.index("Fighting the borrow checker") < archive.index(
        "Generators all the way down"
    )


def test_feed_has_the_newest_posts(site) -> None:
    site.builder().build()
    feed = site.output("feed.xml")

    assert feed.count("<entry>") == 4
    assert "<title>Packaging in 2026</title>" in feed
    assert "Ownership" not in feed
    assert "<updated>2026-03-27T00:00:00Z</updated>" in feed


def test_summary_front_matter_replaces_the_excerpt(site) -> None:
    site.post("summary", "Has a summary", "2026-04-01", ["notes"], summary="Short and sweet.")
    site.builder().build()

    assert "Short and sweet." in site.output("index.html")
    assert "The opening paragraph of has a summary" not in site.output("index.html")


def test_drafts_are_left_out_unless_asked_for(site) -> None:
    site.post("wip", "Work in progress", "2026-04-02", ["notes"], draft="true")

    site.builder().build()
    assert not site.exists("posts/work-in-progress/index.html")

    site.builder(drafts=True).build()
    assert site.exists("posts/work-in-progress/index.html")


def test_two_posts_with_the_same_url_are_an_error(site) -> None:
    site.post("copy", "First steps", "2026-01-01", [])
    with pytest.raises(ContentError, match="both be published"):
        site.builder().build()


def test_cli_build(site, capsys) -> None:
    assert main(["build", str(site.root), "--quiet"]) == 0
    assert capsys.readouterr().out == "wrote 19, unchanged 0, removed 0\n"


def test_cli_reports_errors(tmp_path, capsys) -> None:
    assert main(["build", str(tmp_path)]) == 1
    assert "no site.toml" in capsys.readouterr().err


def test_new_post(site) -> None:
    from datetime import date

    path = new_post(site.root, "Hello Wörld", "a, b", today=date(2026, 5, 1))
    assert path.name == "hello-world.md"
    assert path.read_text(encoding="utf-8").startswith(
        "---\ntitle: Hello Wörld\ndate: 2026-05-01\ntags: [a, b]\n"
    )
