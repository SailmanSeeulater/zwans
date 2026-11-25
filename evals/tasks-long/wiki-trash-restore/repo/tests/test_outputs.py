from xml.etree import ElementTree as ET

from conftest import kitchen
from leafwiki.export import export_markdown, export_site
from leafwiki.feeds import changes_feed, page_feed
from leafwiki.importer import import_folder
from leafwiki.sitemap import sitemap_urls, sitemap_xml
from leafwiki.stats import page_stats, wiki_stats


def items(feed: str) -> list[dict[str, str | None]]:
    root = ET.fromstring(feed)
    return [
        {
            "title": item.findtext("title"),
            "link": item.findtext("link"),
            "category": item.findtext("category"),
        }
        for item in root.iter("item")
    ]


def test_recent_changes_log(wiki) -> None:
    kitchen(wiki)
    wiki.edit_page("Kettle", "Use citric acid.", "bo", "acid is gentler")
    wiki.set_tags("Kettle", ["kitchen"], "bo")
    wiki.rename_page("Teapot", "Tea Pot", "cy")
    wiki.delete_page("Front Page", "ana")
    kinds = [(c.kind, c.title, c.summary) for c in wiki.recent_changes()]
    assert kinds == [
        ("delete", "Front Page", ""),
        ("rename", "Tea Pot", "Teapot → Tea Pot"),
        ("tag", "Kettle", "-appliances"),
        ("edit", "Kettle", "acid is gentler"),
        ("create", "Teapot", ""),
        ("create", "Kettle", ""),
        ("create", "Front Page", ""),
    ]
    assert [c.kind for c in wiki.recent_changes(kinds=["create"])] == ["create"] * 3


def test_the_changes_feed(disk_wiki) -> None:
    kitchen(disk_wiki)
    disk_wiki.edit_page("Kettle", "Use citric acid.", "bo")
    found = items(changes_feed(disk_wiki))
    assert found[0] == {
        "title": "Kettle: edit",
        "link": "https://wiki.example/pages/kettle.html",
        "category": "edit",
    }
    assert [i["title"] for i in found] == [
        "Kettle: edit",
        "Teapot: create",
        "Kettle: create",
        "Front Page: create",
    ]
    assert len(items(changes_feed(disk_wiki, limit=2))) == 2


def test_feed_links_follow_renames(disk_wiki) -> None:
    kitchen(disk_wiki)
    disk_wiki.rename_page("Kettle", "Jug")
    links = {i["title"]: i["link"] for i in items(changes_feed(disk_wiki))}
    assert links["Kettle: create"] == "https://wiki.example/pages/jug.html"


def test_a_page_feed_lists_revisions(disk_wiki) -> None:
    kitchen(disk_wiki)
    disk_wiki.edit_page("Kettle", "v2", "bo", "second")
    found = items(page_feed(disk_wiki, "Kettle"))
    assert [i["title"] for i in found] == ["Kettle: revision 2", "Kettle: revision 1"]


def test_the_sitemap(disk_wiki) -> None:
    kitchen(disk_wiki)
    assert sitemap_urls(sitemap_xml(disk_wiki)) == [
        "https://wiki.example/pages/front-page.html",
        "https://wiki.example/pages/kettle.html",
        "https://wiki.example/pages/teapot.html",
    ]
    assert "<lastmod>2026-03-01</lastmod>" in sitemap_xml(disk_wiki)


def test_the_static_export(wiki, tmp_path) -> None:
    kitchen(wiki)
    wiki.attach("Kettle", "manual.txt", b"read the manual")
    out = tmp_path / "site"
    written = export_site(wiki, out)
    assert "pages/kettle.html" in written
    assert (out / "files" / "kettle" / "manual.txt").read_bytes() == b"read the manual"
    kettle = (out / "pages" / "kettle.html").read_text()
    assert '<a href="front-page.html">Front Page</a>' in kettle  # linked from
    assert '<a href="../tags/kitchen.html">kitchen</a>' in kettle
    front = (out / "pages" / "front-page.html").read_text()
    assert '<a class="wikilink missing" href="toaster.html">Toaster</a>' in front
    assert sorted(p.name for p in (out / "tags").iterdir()) == [
        "appliances.html",
        "home.html",
        "index.html",
        "kitchen.html",
    ]
    assert "Teapot" in (out / "tags" / "kitchen.html").read_text()
    assert 'href="pages/kettle.html"' in (out / "recent.html").read_text()
    assert (out / "sitemap.xml").exists()


def test_markdown_export_and_import_round_trip(wiki, tmp_path, clock) -> None:
    kitchen(wiki)
    names = export_markdown(wiki, tmp_path / "md")
    assert names == ["front-page.md", "kettle.md", "teapot.md"]
    from leafwiki import Wiki

    other = Wiki.memory(clock=clock)
    result = import_folder(other, tmp_path / "md", "ida")
    assert result.created == ["Front Page", "Kettle", "Teapot"]
    assert other.page("Kettle").body.strip() == wiki.page("Kettle").body.strip()
    assert other.page("Kettle").tags == ["appliances", "kitchen"]
    again = import_folder(other, tmp_path / "md", "ida")
    assert again.unchanged == ["Front Page", "Kettle", "Teapot"]


def test_wiki_stats(wiki) -> None:
    kitchen(wiki)
    wiki.attach("Kettle", "a.bin", b"12345")
    wiki.comment("Teapot", "hi", "ana")
    wiki.create_page("Lonely", "Nobody links here. [[Kettle]]", "dee")
    stats = wiki_stats(wiki)
    assert stats["pages"] == 4
    assert stats["revisions"] == 4
    assert stats["attachments"] == 1
    assert stats["attachment_bytes"] == 5
    assert stats["comments"] == 1
    assert stats["tags"] == 3
    assert stats["authors"] == 4
    assert stats["top_linked"] == [["Kettle", 3], ["Front Page", 1], ["Teapot", 1]]
    assert stats["orphans"] == ["Lonely"]
    assert stats["wanted"] == ["Toaster"]


def test_page_stats(wiki) -> None:
    kitchen(wiki)
    wiki.edit_page("Kettle", "Short now. [[Teapot]]", "ana")
    wiki.watch("Kettle", "cy")
    stats = page_stats(wiki, "kettle")
    assert stats["revisions"] == 2
    assert stats["authors"] == ["ana", "bo"]
    assert stats["words"] == 3
    assert stats["backlinks"] == 2
    assert stats["watchers"] == 1
