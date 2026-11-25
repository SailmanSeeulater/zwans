import pytest
from conftest import entries, kitchen, snapshot, stocked
from leafwiki import PageExists, PageNotFound, Wiki, WikiError
from leafwiki.errors import TrashEntryNotFound


def test_delete_returns_an_entry_id_and_lists_it(manual) -> None:
    wiki = Wiki.memory(clock=manual)
    kitchen(wiki)
    manual.advance(minutes=5)
    first = wiki.delete_page("kettle", "ana")
    manual.advance(minutes=5)
    second = wiki.delete_page("Teapot", "bo")
    assert isinstance(first, str) and isinstance(second, str) and first != second
    listed = list(wiki.trash())
    assert [(e.id, e.title, e.deleted_at, e.deleted_by) for e in listed] == [
        (second, "Teapot", "2026-03-01T09:10:00Z", "bo"),
        (first, "Kettle", "2026-03-01T09:05:00Z", "ana"),
    ]


def test_a_trashed_page_is_not_there(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.delete_page("Kettle", "ana")
    assert not wiki.exists("Kettle")
    assert wiki.titles() == ["Front Page", "Teapot"]
    assert [p.title for p in wiki.pages()] == ["Front Page", "Teapot"]
    calls = [
        lambda: wiki.page("Kettle"),
        lambda: wiki.history("Kettle"),
        lambda: wiki.revision("Kettle", 1),
        lambda: wiki.comments("Kettle"),
        lambda: wiki.watchers("Kettle"),
        lambda: wiki.attachments("Kettle"),
        lambda: wiki.attachment("Kettle", "manual.txt"),
        lambda: wiki.links("Kettle"),
        lambda: wiki.render("Kettle"),
        lambda: wiki.edit_page("Kettle", "back?"),
        lambda: wiki.rename_page("Kettle", "Jug"),
        lambda: wiki.set_tags("Kettle", ["x"]),
        lambda: wiki.comment("Kettle", "hello?", "cy"),
        lambda: wiki.attach("Kettle", "x.txt", b"x"),
        lambda: wiki.watch("Kettle", "eve"),
        lambda: wiki.revert("Kettle", 1),
    ]
    for call in calls:
        with pytest.raises(PageNotFound):
            call()


def test_restore_brings_back_everything_exactly(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    before = snapshot(wiki, "Kettle")
    entry = wiki.delete_page("Kettle", "ana")
    page = wiki.restore_page(entry, "bo")
    assert page.to_dict() == before["page"]
    assert snapshot(wiki, "Kettle") == before
    assert page.id == "p2"
    assert [r.number for r in wiki.history("Kettle")] == [1, 2]
    assert list(wiki.trash()) == []
    assert wiki.titles() == ["Front Page", "Kettle", "Teapot"]


def test_restored_comments_still_work(wiki) -> None:
    stocked(wiki)
    wiki.restore_page(wiki.delete_page("Kettle"))
    first, reply = wiki.comments("Kettle")
    wiki.comment("Kettle", "Thanks!", "dee", reply_to=reply.id)
    wiki.edit_comment(first.id, "Edited after the restore.")
    assert wiki.delete_comment(first.id) == 3
    assert wiki.comments("Kettle") == []


def test_unknown_entries(wiki) -> None:
    kitchen(wiki)
    with pytest.raises(TrashEntryNotFound) as caught:
        wiki.restore_page("t999")
    assert isinstance(caught.value, WikiError) and isinstance(caught.value, LookupError)
    with pytest.raises(TrashEntryNotFound):
        wiki.purge_page("t999")
    entry = wiki.delete_page("Kettle")
    wiki.restore_page(entry)
    with pytest.raises(TrashEntryNotFound):
        wiki.restore_page(entry)
    entry = wiki.delete_page("Kettle")
    wiki.purge_page(entry)
    with pytest.raises(TrashEntryNotFound):
        wiki.restore_page(entry)
    with pytest.raises(TrashEntryNotFound):
        wiki.purge_page(entry)
    assert list(wiki.trash()) == []


def test_the_title_of_a_trashed_page_is_free(wiki) -> None:
    kitchen(wiki)
    old = wiki.delete_page("Kettle", "ana")
    new = wiki.create_page("kettle", "A brand new kettle page.", "bo")
    assert new.id != "p2"
    assert wiki.page("Kettle").body == "A brand new kettle page."
    with pytest.raises(PageExists):
        wiki.restore_page(old)
    assert [e.id for e in wiki.trash()] == [old]
    restored = wiki.restore_page(old, "cy", title="Old Kettle")
    assert restored.title == "Old Kettle"
    assert restored.id == "p2"
    assert restored.body.startswith("Descale the kettle")
    assert wiki.titles() == ["Front Page", "kettle", "Old Kettle", "Teapot"]


def test_renaming_onto_a_trashed_title(wiki) -> None:
    kitchen(wiki)
    entry = wiki.delete_page("Teapot")
    wiki.rename_page("Kettle", "Teapot")
    assert wiki.titles() == ["Front Page", "Teapot"]
    with pytest.raises(PageExists):
        wiki.restore_page(entry)
    wiki.rename_page("Teapot", "Kettle")
    assert wiki.restore_page(entry).title == "Teapot"


def test_restore_under_another_title_changes_only_the_title(wiki) -> None:
    stocked(wiki)
    before = snapshot(wiki, "Kettle")
    entry = wiki.delete_page("Kettle")
    wiki.restore_page(entry, title="Jug")
    after = snapshot(wiki, "Jug")
    assert after["page"]["title"] == "Jug"
    after["page"]["title"] = "Kettle"
    assert after == before


def test_purge_removes_the_entry(wiki) -> None:
    kitchen(wiki)
    keep = wiki.delete_page("Teapot")
    gone = wiki.delete_page("Kettle")
    wiki.purge_page(gone, "ana")
    assert [e.id for e in wiki.trash()] == [keep]
    assert wiki.titles() == ["Front Page"]


def test_the_trash_survives_reopening(disk_wiki, folder, clock) -> None:
    stocked(disk_wiki)
    before = snapshot(disk_wiki, "Kettle")
    entry = disk_wiki.delete_page("Kettle", "ana")
    listed = entries(disk_wiki)
    again = Wiki.open(folder, clock=clock)
    assert entries(again) == listed
    assert again.titles() == ["Front Page", "Teapot"]
    again.restore_page(entry)
    assert snapshot(again, "Kettle") == before
    assert snapshot(Wiki.open(folder, clock=clock), "Kettle") == before


def test_ids_keep_counting_after_a_restore(wiki) -> None:
    kitchen(wiki)
    wiki.restore_page(wiki.delete_page("Kettle"))
    assert wiki.create_page("Toaster", "x").id == "p4"
