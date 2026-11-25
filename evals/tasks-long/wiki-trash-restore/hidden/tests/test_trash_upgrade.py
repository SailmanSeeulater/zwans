from conftest import START, ManualClock
from leafwiki import Wiki
from leafwiki.doctor import check


def test_pages_deleted_in_1x_land_in_the_trash(legacy_folder) -> None:
    wiki = Wiki.open(legacy_folder, clock=ManualClock())
    assert wiki.titles() == ["Compost", "Front Page", "Potatoes"]
    (entry,) = wiki.trash()
    assert entry.title == "Old Shed"
    assert entry.deleted_by == "upgrade"
    assert entry.deleted_at == "2026-03-01T09:00:00Z"
    assert check(wiki) == []
    assert wiki.search("wheelbarrow") == []


def test_they_can_be_restored_with_their_history_and_comments(legacy_folder) -> None:
    wiki = Wiki.open(legacy_folder, clock=ManualClock())
    (entry,) = wiki.trash()
    page = wiki.restore_page(entry.id, "ida")
    assert page.title == "Old Shed"
    assert page.tags == ["structures"]
    assert [(r.number, r.author, r.summary) for r in page.revisions] == [
        (1, "jon", "Created"),
        (2, "ida", "gone"),
    ]
    assert page.revisions[0].body == "The shed by the gate leaks; the felt roof needs replacing."
    assert [c.text for c in wiki.comments("Old Shed")] == ["I can bring roofing felt on Saturday."]
    assert wiki.backlinks("Compost") == ["Front Page", "Old Shed"]
    assert [h.title for h in wiki.search("wheelbarrow")] == ["Old Shed"]
    assert check(wiki) == []


def test_the_upgraded_trash_is_saved(legacy_folder) -> None:
    clock = ManualClock()
    Wiki.open(legacy_folder, clock=clock)
    again = Wiki.open(legacy_folder, clock=clock)
    assert [e.title for e in again.trash()] == ["Old Shed"]
    assert again.titles() == ["Compost", "Front Page", "Potatoes"]


def test_page_ids_stay_unique_after_the_upgrade(legacy_folder) -> None:
    wiki = Wiki.open(legacy_folder, clock=ManualClock())
    (entry,) = wiki.trash()
    new = wiki.create_page("Greenhouse", "Glass.")
    page = wiki.restore_page(entry.id)
    ids = [p.id for p in wiki.pages()]
    assert len(set(ids)) == len(ids) == 5
    assert new.id != page.id


def test_upgraded_entries_expire_like_any_other(legacy_folder) -> None:
    clock = ManualClock(START)
    wiki = Wiki.open(legacy_folder, clock=clock)
    clock.advance(days=31)
    assert wiki.maintain().trash_purged == 1
    assert list(wiki.trash()) == []
