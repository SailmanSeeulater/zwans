from pathlib import Path
from xml.etree import ElementTree as ET

from conftest import BODY_MARK, FILE_MARK, kitchen, stocked
from leafwiki.export import export_markdown, export_site
from leafwiki.feeds import changes_feed
from leafwiki.sitemap import sitemap_urls, sitemap_xml

KETTLE = "https://wiki.example/pages/kettle.html"


def items(feed: str) -> list[dict[str, str | None]]:
    root = ET.fromstring(feed)
    return [
        {"title": item.findtext("title"), "link": item.findtext("link")}
        for item in root.iter("item")
    ]


def everything_in(folder: Path) -> bytes:
    return b"\n".join(p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file())


def test_the_sitemap_leaves_out_the_trash(disk_wiki) -> None:
    kitchen(disk_wiki)
    entry = disk_wiki.delete_page("Kettle")
    assert sitemap_urls(sitemap_xml(disk_wiki)) == [
        "https://wiki.example/pages/front-page.html",
        "https://wiki.example/pages/teapot.html",
    ]
    disk_wiki.restore_page(entry)
    assert KETTLE in sitemap_urls(sitemap_xml(disk_wiki))


def test_the_static_export_leaves_out_the_trash(wiki, tmp_path) -> None:
    stocked(wiki)
    entry = wiki.delete_page("Kettle", "ana")
    out = tmp_path / "site"
    written = export_site(wiki, out)
    assert not any("kettle" in name for name in written if name.startswith(("pages/", "files/")))
    assert not (out / "pages" / "kettle.html").exists()
    assert not (out / "files" / "kettle").exists()
    blob = everything_in(out)
    assert BODY_MARK.encode() not in blob
    assert FILE_MARK not in blob
    front = (out / "pages" / "front-page.html").read_text()
    assert '<a class="wikilink missing" href="kettle.html">Kettle</a>' in front
    assert "Linked from" not in front
    assert "Kettle" not in (out / "tags" / "kitchen.html").read_text()
    assert not (out / "tags" / "appliances.html").exists()
    assert "kettle.html" not in (out / "index.html").read_text()
    assert "pages/kettle.html" not in (out / "recent.html").read_text()

    wiki.restore_page(entry)
    export_site(wiki, out)
    assert FILE_MARK in (out / "files" / "kettle" / "manual.txt").read_bytes()
    assert BODY_MARK in (out / "pages" / "kettle.html").read_text()
    assert '<a class="wikilink" href="kettle.html">Kettle</a>' in (
        out / "pages" / "front-page.html"
    ).read_text()
    assert "Kettle" in (out / "tags" / "kitchen.html").read_text()


def test_the_markdown_export_leaves_out_the_trash(wiki, tmp_path) -> None:
    stocked(wiki)
    entry = wiki.delete_page("Kettle")
    assert export_markdown(wiki, tmp_path / "md") == ["front-page.md", "teapot.md"]
    wiki.restore_page(entry)
    assert "kettle.md" in export_markdown(wiki, tmp_path / "md2")


def test_feed_items_about_a_trashed_page_have_no_link(disk_wiki) -> None:
    kitchen(disk_wiki)
    disk_wiki.edit_page("Kettle", "Use citric acid.", "bo")
    entry = disk_wiki.delete_page("Kettle", "ana")
    found = items(changes_feed(disk_wiki))
    about = [i for i in found if i["title"].startswith("Kettle:")]
    assert [i["title"] for i in about] == ["Kettle: delete", "Kettle: edit", "Kettle: create"]
    assert all(i["link"] is None for i in about)
    others = [i for i in found if not i["title"].startswith("Kettle:")]
    assert all(i["link"] for i in others)

    disk_wiki.restore_page(entry, "ana")
    about = [i for i in items(changes_feed(disk_wiki)) if i["title"].startswith("Kettle:")]
    assert [i["title"] for i in about][0] == "Kettle: restore"
    assert all(i["link"] == KETTLE for i in about)


def test_feed_items_about_a_purged_page_have_no_link(disk_wiki) -> None:
    kitchen(disk_wiki)
    disk_wiki.purge_page(disk_wiki.delete_page("Teapot"))
    about = [i for i in items(changes_feed(disk_wiki)) if i["title"].startswith("Teapot:")]
    assert [i["title"] for i in about] == ["Teapot: purge", "Teapot: delete", "Teapot: create"]
    assert all(i["link"] is None for i in about)


def test_recent_changes_log_restore_and_purge(wiki) -> None:
    kitchen(wiki)
    first = wiki.delete_page("Kettle", "ana")
    wiki.create_page("Kettle", "new one", "bo")
    wiki.restore_page(first, "cy", title="Old Kettle")
    wiki.purge_page(wiki.delete_page("Teapot", "dee"), "eve")
    log = [(c.kind, c.title, c.author) for c in wiki.recent_changes(limit=6)]
    assert log == [
        ("purge", "Teapot", "eve"),
        ("delete", "Teapot", "dee"),
        ("restore", "Old Kettle", "cy"),
        ("create", "Kettle", "bo"),
        ("delete", "Kettle", "ana"),
        ("create", "Teapot", "cy"),
    ]
    assert [c.kind for c in wiki.recent_changes(kinds=["restore", "purge"])] == ["purge", "restore"]
