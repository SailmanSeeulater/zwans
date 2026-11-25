from pathlib import Path

from conftest import BODY_MARK, COMMENT_MARK, FILE_MARK, entries, kitchen, snapshot, stocked
from leafwiki import Wiki
from leafwiki.backup import create_backup, restore_backup
from leafwiki.doctor import check


def everything_in(folder: Path) -> bytes:
    return b"\n".join(p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file())


def test_purge_leaves_nothing_behind(disk_wiki, folder, clock) -> None:
    stocked(disk_wiki)
    entry = disk_wiki.delete_page("Kettle", "ana")
    kept = everything_in(folder)
    for mark in (BODY_MARK.encode(), FILE_MARK, COMMENT_MARK.encode()):
        assert mark in kept  # the trash still has it all
    disk_wiki.purge_page(entry, "ana")
    left = everything_in(folder)
    assert BODY_MARK.encode() not in left
    assert FILE_MARK not in left
    assert COMMENT_MARK.encode() not in left
    again = Wiki.open(folder, clock=clock)
    assert list(again.trash()) == []
    assert again.search(BODY_MARK) == []


def test_purge_keeps_contents_another_live_page_uses(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.attach("Teapot", "copy.txt", FILE_MARK + b" read the manual")
    wiki.purge_page(wiki.delete_page("Kettle"))
    assert wiki.attachment("Teapot", "copy.txt") == FILE_MARK + b" read the manual"
    assert check(wiki) == []


def test_purge_keeps_contents_another_trashed_page_uses(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.attach("Teapot", "copy.txt", FILE_MARK + b" read the manual")
    teapot = wiki.delete_page("Teapot")
    wiki.purge_page(wiki.delete_page("Kettle"))
    wiki.restore_page(teapot)
    assert wiki.attachment("Teapot", "copy.txt") == FILE_MARK + b" read the manual"


def test_backups_carry_the_trash(disk_wiki, tmp_path, clock) -> None:
    stocked(disk_wiki)
    before = snapshot(disk_wiki, "Kettle")
    entry = disk_wiki.delete_page("Kettle", "ana")
    create_backup(disk_wiki, tmp_path / "b.zip")
    restored = restore_backup(tmp_path / "b.zip", tmp_path / "copy", clock=clock)
    assert entries(restored) == entries(disk_wiki)
    assert restored.titles() == ["Front Page", "Teapot"]
    assert restored.search(BODY_MARK) == []
    restored.restore_page(entry)
    assert snapshot(restored, "Kettle") == before
    assert check(restored) == []


def test_check_is_happy_with_the_trash(disk_wiki, folder, clock) -> None:
    stocked(disk_wiki)
    entry = disk_wiki.delete_page("Kettle", "ana")
    assert check(disk_wiki) == []
    assert check(Wiki.open(folder, clock=clock)) == []
    disk_wiki.restore_page(entry)
    assert check(Wiki.open(folder, clock=clock)) == []
    disk_wiki.purge_page(disk_wiki.delete_page("Kettle"))
    assert check(Wiki.open(folder, clock=clock)) == []


def test_two_trashed_pages_with_the_same_title(wiki) -> None:
    kitchen(wiki)
    first = wiki.delete_page("Kettle")
    wiki.create_page("Kettle", "second kettle")
    second = wiki.delete_page("Kettle")
    assert [e.title for e in wiki.trash()] == ["Kettle", "Kettle"]
    assert wiki.restore_page(first).body.startswith("Descale")
    assert wiki.restore_page(second, title="Kettle Two").body == "second kettle"
