from conftest import kitchen, stocked
from leafwiki import Wiki


def test_backlinks_from_a_trashed_page_disappear_and_come_back(wiki) -> None:
    kitchen(wiki)
    assert wiki.backlinks("Front Page") == ["Kettle"]
    assert wiki.backlinks("Kettle") == ["Front Page", "Teapot"]
    entry = wiki.delete_page("Teapot")
    assert wiki.backlinks("Kettle") == ["Front Page"]
    wiki.restore_page(entry)
    assert wiki.backlinks("Kettle") == ["Front Page", "Teapot"]
    entry = wiki.delete_page("Kettle")
    assert wiki.backlinks("Front Page") == []
    wiki.restore_page(entry)
    assert wiki.backlinks("Front Page") == ["Kettle"]


def test_backlinks_after_reopening(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    entry = disk_wiki.delete_page("Teapot")
    again = Wiki.open(folder, clock=clock)
    assert again.backlinks("Kettle") == ["Front Page"]
    again.restore_page(entry)
    assert Wiki.open(folder, clock=clock).backlinks("Kettle") == ["Front Page", "Teapot"]


def test_links_to_a_trashed_page_are_missing(wiki) -> None:
    kitchen(wiki)
    entry = wiki.delete_page("Kettle")
    html = wiki.render("Front Page")
    assert 'class="wikilink missing" href="/pages/kettle"' in html
    assert [(l.target, l.exists) for l in wiki.links("Front Page")][0] == ("Kettle", False)
    assert "kettle" in wiki.wanted()
    assert wiki.wanted()["kettle"] == ["Front Page", "Teapot"]
    wiki.restore_page(entry)
    assert 'class="wikilink" href="/pages/kettle"' in wiki.render("Front Page")
    assert "kettle" not in wiki.wanted()


def test_orphans_ignore_links_from_the_trash(wiki) -> None:
    kitchen(wiki)
    entry = wiki.delete_page("Kettle")
    assert wiki.orphans() == ["Front Page"]
    wiki.restore_page(entry)
    assert wiki.orphans() == []


def test_tags_of_a_trashed_page_are_not_counted(any_wiki) -> None:
    wiki = any_wiki
    kitchen(wiki)
    entry = wiki.delete_page("Kettle")
    assert wiki.tags() == {"home": 1, "kitchen": 1}
    assert wiki.pages_tagged("kitchen") == ["Teapot"]
    assert wiki.pages_tagged("appliances") == []
    wiki.restore_page(entry)
    assert wiki.tags() == {"appliances": 1, "home": 1, "kitchen": 2}
    assert wiki.pages_tagged("kitchen") == ["Kettle", "Teapot"]


def test_tags_after_reopening(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    entry = disk_wiki.delete_page("Kettle")
    again = Wiki.open(folder, clock=clock)
    assert again.tags() == {"home": 1, "kitchen": 1}
    again.restore_page(entry)
    assert Wiki.open(folder, clock=clock).pages_tagged("appliances") == ["Kettle"]


def test_watched_by_skips_the_trash(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.watch("Teapot", "cy")
    entry = wiki.delete_page("Kettle", "ana")
    assert wiki.watched_by("cy") == ["Teapot"]
    assert wiki.watched_by("dee") == []
    wiki.restore_page(entry, "ana")
    assert wiki.watched_by("cy") == ["Kettle", "Teapot"]
    assert wiki.watchers("Kettle") == ["cy", "dee"]


def test_recent_comments_skip_the_trash(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.comment("Teapot", "Lovely pot.", "eve")
    entry = wiki.delete_page("Kettle")
    assert [(t, c.text) for t, c in wiki.recent_comments()] == [("Teapot", "Lovely pot.")]
    wiki.restore_page(entry)
    assert [t for t, _ in wiki.recent_comments()] == ["Teapot", "Kettle", "Kettle"]
