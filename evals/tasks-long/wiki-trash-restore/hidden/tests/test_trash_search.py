from conftest import BODY_MARK, kitchen, stocked, titles
from leafwiki import Wiki
from leafwiki.doctor import check


def test_live_search_forgets_and_remembers(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    assert titles(wiki.search(BODY_MARK)) == ["Kettle"]
    entry = wiki.delete_page("Kettle")
    assert wiki.search(BODY_MARK) == []
    assert wiki.search("title:kettle") == []
    assert titles(wiki.search("tag:kitchen")) == ["Teapot"]
    assert titles(wiki.search("kettle")) == ["Teapot", "Front Page"]
    wiki.restore_page(entry)
    assert titles(wiki.search(BODY_MARK)) == ["Kettle"]
    assert titles(wiki.search("tag:appliances")) == ["Kettle"]
    assert titles(wiki.search("kettle")) == ["Kettle", "Teapot", "Front Page"]


def test_search_after_reopening(disk_wiki, folder, clock) -> None:
    stocked(disk_wiki)
    entry = disk_wiki.delete_page("Kettle")
    again = Wiki.open(folder, clock=clock)
    assert again.search(BODY_MARK) == []
    again.restore_page(entry)
    assert titles(Wiki.open(folder, clock=clock).search(BODY_MARK)) == ["Kettle"]


def test_search_after_rebuilding(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    entry = wiki.delete_page("Kettle")
    wiki.rebuild_index()
    assert wiki.search(BODY_MARK) == []
    wiki.restore_page(entry)
    wiki.rebuild_index()
    assert titles(wiki.search(BODY_MARK)) == ["Kettle"]


def test_reopening_with_a_missing_index_rebuilds_without_the_trash(disk_wiki, folder, clock) -> None:
    stocked(disk_wiki)
    entry = disk_wiki.delete_page("Kettle")
    (folder / "index.json").unlink(missing_ok=True)
    again = Wiki.open(folder, clock=clock)
    assert again.search(BODY_MARK) == []
    again.restore_page(entry)
    (folder / "index.json").unlink(missing_ok=True)
    assert titles(Wiki.open(folder, clock=clock).search(BODY_MARK)) == ["Kettle"]


def test_a_restored_page_under_a_new_title_is_found_by_it(wiki) -> None:
    kitchen(wiki)
    entry = wiki.delete_page("Kettle")
    wiki.create_page("Kettle", "Another kettle entirely.")
    wiki.restore_page(entry, title="Stovetop Kettle")
    assert titles(wiki.search("title:stovetop")) == ["Stovetop Kettle"]
    assert titles(wiki.search("vinegar")) == ["Stovetop Kettle"]


def test_the_index_stays_consistent(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    entry = wiki.delete_page("Kettle")
    assert check(wiki) == []
    wiki.restore_page(entry)
    assert check(wiki) == []
    wiki.purge_page(wiki.delete_page("Teapot"))
    assert check(wiki) == []
