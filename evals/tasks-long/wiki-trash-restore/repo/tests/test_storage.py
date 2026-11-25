import json
import zipfile

import pytest
from conftest import kitchen
from leafwiki import Wiki
from leafwiki.backup import create_backup, restore_backup
from leafwiki.doctor import check
from leafwiki.errors import StoreError


def test_a_wiki_survives_reopening(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    disk_wiki.attach("Kettle", "manual.txt", b"read me")
    disk_wiki.comment("Kettle", "nice", "cy")
    disk_wiki.watch("Teapot", "dee")
    again = Wiki.open(folder, clock=clock)
    assert again.titles() == ["Front Page", "Kettle", "Teapot"]
    assert again.attachment("Kettle", "manual.txt") == b"read me"
    assert [c.text for c in again.comments("Kettle")] == ["nice"]
    assert again.watchers("Teapot") == ["dee"]
    assert again.backlinks("Kettle") == ["Front Page", "Teapot"]
    assert again.tags() == disk_wiki.tags()
    assert again.settings.site_name == "Test Wiki"
    assert again.create_page("Toaster", "x").id == "p4"


def test_the_manifest_says_format_2(disk_wiki, folder) -> None:
    assert json.loads((folder / "wiki.json").read_text())["format"] == 2


def test_a_folder_without_a_wiki_is_refused(tmp_path) -> None:
    with pytest.raises(StoreError):
        Wiki.open(tmp_path)


def test_a_newer_format_is_refused(folder, disk_wiki) -> None:
    (folder / "wiki.json").write_text('{"format": 3}')
    with pytest.raises(StoreError):
        Wiki.open(folder)


def test_a_1x_wiki_is_upgraded(legacy_folder, clock) -> None:
    wiki = Wiki.open(legacy_folder, clock=clock)
    assert wiki.titles() == ["Compost", "Front Page", "Potatoes"]
    assert [r.author for r in wiki.history("Front Page")] == ["ida", "jon"]
    assert wiki.page("Potatoes").tags == ["spring", "veg"]
    assert [c.text for c in wiki.comments("Potatoes")] == ["Maris Piper did best last year."]
    assert wiki.settings.site_name == "Allotment Notes"
    assert json.loads((legacy_folder / "wiki.json").read_text())["format"] == 2
    assert wiki.backlinks("Compost") == ["Front Page"]
    assert [h.title for h in wiki.search("chit")] == ["Potatoes"]
    assert check(wiki) == []
    again = Wiki.open(legacy_folder, clock=clock)
    assert again.titles() == wiki.titles()


def test_backups_round_trip(disk_wiki, tmp_path, clock) -> None:
    kitchen(disk_wiki)
    disk_wiki.attach("Teapot", "leaf.png", b"\x89PNG tea")
    disk_wiki.comment("Teapot", "lovely", "dee")
    disk_wiki.watch("Kettle", "dee")
    counts = create_backup(disk_wiki, tmp_path / "b.zip")
    assert counts == {"pages": 3, "attachments": 1, "comments": 1, "changes": 5}
    with zipfile.ZipFile(tmp_path / "b.zip") as archive:
        assert "backup.json" in archive.namelist()
    restored = restore_backup(tmp_path / "b.zip", tmp_path / "copy", clock=clock)
    assert restored.titles() == disk_wiki.titles()
    assert restored.attachment("Teapot", "leaf.png") == b"\x89PNG tea"
    assert restored.watchers("Kettle") == ["dee"]
    assert [c.text for c in restored.comments("Teapot")] == ["lovely"]
    assert [h.title for h in restored.search("vinegar")] == ["Kettle"]
    assert restored.recent_changes() == disk_wiki.recent_changes()
    assert check(restored) == []


def test_restoring_needs_an_empty_folder(disk_wiki, tmp_path) -> None:
    create_backup(disk_wiki, tmp_path / "b.zip")
    target = tmp_path / "busy"
    target.mkdir()
    (target / "x").write_text("x")
    with pytest.raises(StoreError):
        restore_backup(tmp_path / "b.zip", target)


def test_check_finds_damage(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    disk_wiki.attach("Kettle", "a.txt", b"hello")
    assert check(disk_wiki) == []
    for blob in (folder / "blobs").rglob("*"):
        if blob.is_file():
            blob.unlink()
    (folder / "comments" / "p99.json").parent.mkdir(exist_ok=True)
    (folder / "comments" / "p99.json").write_text("[]")
    problems = check(Wiki.open(folder, clock=clock))
    assert "Kettle: attachment a.txt has no content" in problems
    assert any("p99" in p for p in problems)
