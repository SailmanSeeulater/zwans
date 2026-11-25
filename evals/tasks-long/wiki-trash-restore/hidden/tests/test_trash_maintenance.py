import pytest
from conftest import FILE_MARK, ManualClock, kitchen, snapshot, stocked
from leafwiki import Wiki
from leafwiki.errors import InvalidSetting


@pytest.fixture
def timed() -> tuple[Wiki, ManualClock]:
    clock = ManualClock()
    wiki = Wiki.memory(clock=clock)
    stocked(wiki)
    return wiki, clock


def test_entries_are_purged_after_the_retention(timed) -> None:
    wiki, clock = timed
    entry = wiki.delete_page("Kettle", "ana")
    clock.advance(days=30)
    report = wiki.maintain()
    assert report.trash_purged == 0
    assert [e.id for e in wiki.trash()] == [entry]
    clock.advance(minutes=1)
    assert wiki.maintain().trash_purged == 1
    assert list(wiki.trash()) == []


def test_only_old_entries_go(timed) -> None:
    wiki, clock = timed
    wiki.delete_page("Kettle")
    clock.advance(days=20)
    young = wiki.delete_page("Teapot")
    clock.advance(days=15)
    assert wiki.maintain().trash_purged == 1
    assert [e.id for e in wiki.trash()] == [young]


def test_the_retention_is_a_setting(timed) -> None:
    wiki, clock = timed
    assert wiki.settings.trash_retention_days == 30
    wiki.set_setting("trash_retention_days", 7)
    wiki.delete_page("Kettle")
    clock.advance(days=8)
    assert wiki.maintain().trash_purged == 1
    with pytest.raises(InvalidSetting):
        wiki.set_setting("trash_retention_days", 0)


def test_the_setting_is_saved(disk_wiki, folder, clock) -> None:
    disk_wiki.set_setting("trash_retention_days", 3)
    assert Wiki.open(folder, clock=clock).settings.trash_retention_days == 3


def test_maintenance_keeps_trashed_attachment_contents(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    entry = wiki.delete_page("Kettle")
    assert wiki.maintain().blobs_removed == 0
    wiki.restore_page(entry)
    assert wiki.attachment("Kettle", "manual.txt") == FILE_MARK + b" read the manual"


def test_detached_contents_still_go(wiki) -> None:
    stocked(wiki)
    wiki.attach("Teapot", "spare.txt", b"spare")
    wiki.detach("Teapot", "spare.txt")
    wiki.delete_page("Kettle")
    assert wiki.maintain().blobs_removed == 1


def test_revision_pruning_skips_the_trash(wiki) -> None:
    kitchen(wiki)
    for n in range(4):
        wiki.edit_page("Kettle", f"version {n}")
        wiki.edit_page("Teapot", f"version {n}")
    before = snapshot(wiki, "Kettle")
    entry = wiki.delete_page("Kettle")
    wiki.set_setting("keep_revisions", 2)
    assert wiki.maintain().revisions_pruned == 3
    wiki.restore_page(entry)
    assert snapshot(wiki, "Kettle") == before
    assert len(wiki.history("Kettle")) == 5


def test_a_purge_by_maintenance_removes_the_contents(folder) -> None:
    clock = ManualClock()
    wiki = Wiki.init(folder, clock=clock)
    stocked(wiki)
    wiki.delete_page("Kettle")
    clock.advance(days=40)
    wiki.maintain()
    files = [p.read_bytes() for p in folder.rglob("*") if p.is_file()]
    assert not any(FILE_MARK in data for data in files)
