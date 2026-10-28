from sitegen.serve import Watcher


def test_a_rebuild_without_changes_writes_nothing(site) -> None:
    site.builder().build()

    report = site.builder().build()

    assert report.written == []
    assert len(report.unchanged) == 19


def test_editing_a_later_paragraph_only_rewrites_that_post(site) -> None:
    site.builder().build()
    site.edit("borrowck", "A closing paragraph.", "A closing paragraph, now with more lifetimes.")

    report = site.builder().build()

    assert report.written == ["posts/fighting-the-borrow-checker/index.html"]
    assert "more lifetimes" in site.output("posts/fighting-the-borrow-checker/index.html")


def test_a_new_post_rewrites_the_listings_it_appears_on(site) -> None:
    site.builder().build()
    site.post("pattern-matching", "Pattern matching", "2026-04-10", ["python"])

    report = site.builder().build()

    assert set(report.written) == {
        "posts/pattern-matching/index.html",
        "index.html",
        "page/2/index.html",
        "page/3/index.html",
        "tags/python/index.html",
        "tags/index.html",
        "archive/index.html",
        "feed.xml",
        "sitemap.xml",
    }
    assert "Pattern matching" in site.output("tags/python/index.html")


def test_removing_the_last_post_of_a_tag_removes_the_tag_page(site) -> None:
    site.builder().build()
    site.edit("static-sites", "tags: [web]", "tags: []")
    site.edit("asyncio-tour", "tags: [python, web]", "tags: [python]")

    report = site.builder().build()

    assert report.removed == ["tags/web/index.html"]
    assert not site.exists("tags/web/index.html")
    assert not (site.root / "public" / "tags" / "web").exists()


def test_changing_a_template_rewrites_everything(site) -> None:
    site.builder().build()
    site.write("templates/foot.html", "</main><footer>new footer</footer></body></html>\n")

    report = site.builder().build()

    assert len([path for path in report.written if path.endswith(".html")]) == 17
    assert "new footer" in site.output("posts/first-steps/index.html")


def test_changing_a_setting_rewrites_everything_that_shows_it(site) -> None:
    site.builder().build()
    site.write(
        "site.toml", site.root.joinpath("site.toml").read_text("utf-8").replace("Robin", "R.")
    )

    written = site.builder().build().written

    assert len([path for path in written if path.endswith(".html")]) == 17
    assert "feed.xml" in written
    assert "<name>R.</name>" in site.output("feed.xml")


def test_clean_build(site) -> None:
    site.builder().build()
    (site.root / "public" / "leftover.txt").write_text("x", encoding="utf-8")

    report = site.builder().build(clean=True)

    assert len(report.written) == 19
    assert not (site.root / "public" / "leftover.txt").exists()


def test_static_files_are_copied_when_they_change(site) -> None:
    site.write("static/style.css", "body { color: black }\n")
    site.builder().build()
    assert site.output("static/style.css") == "body { color: black }\n"

    site.write("static/style.css", "body { color: navy }\n")
    report = site.builder().build()

    assert report.written == ["static/style.css"]


def test_serve_rebuilds_when_a_file_changes(site) -> None:
    builder = site.builder()
    builder.build()
    watcher = Watcher(builder)

    assert watcher.poll_once() is None

    site.post("pattern-matching", "Pattern matching", "2026-04-10", ["python"])
    report = watcher.poll_once()

    assert report is not None
    assert "posts/pattern-matching/index.html" in report.written
    assert "Pattern matching" in site.output("index.html")
    assert watcher.poll_once() is None
