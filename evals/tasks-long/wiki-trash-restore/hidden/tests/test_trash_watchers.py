from conftest import ManualClock, kitchen, stocked
from leafwiki import Wiki


def events(wiki: Wiki) -> list[tuple[str, str, str, str]]:
    return [(m.to, m.event, m.page, m.by) for m in wiki.drain_outbox()]


def test_delete_restore_purge_notify_the_watchers(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.drain_outbox()
    entry = wiki.delete_page("Kettle", "cy")
    assert events(wiki) == [("dee", "deleted", "Kettle", "cy")]
    wiki.restore_page(entry, "dee")
    assert events(wiki) == [("cy", "restored", "Kettle", "dee")]
    entry = wiki.delete_page("Kettle", "ana")
    assert events(wiki) == [("cy", "deleted", "Kettle", "ana"), ("dee", "deleted", "Kettle", "ana")]
    wiki.purge_page(entry, "eve")
    assert events(wiki) == [("cy", "purged", "Kettle", "eve"), ("dee", "purged", "Kettle", "eve")]


def test_restored_watchers_keep_getting_notified(wiki) -> None:
    stocked(wiki)
    wiki.restore_page(wiki.delete_page("Kettle", "ana"), "ana")
    wiki.drain_outbox()
    wiki.edit_page("Kettle", "Changed after coming back.", "dee")
    assert events(wiki) == [("cy", "edited", "Kettle", "dee")]


def test_restoring_under_a_new_title_notifies_with_it(wiki) -> None:
    stocked(wiki)
    entry = wiki.delete_page("Kettle", "ana")
    wiki.drain_outbox()
    wiki.restore_page(entry, "ana", title="Jug")
    assert events(wiki) == [("cy", "restored", "Jug", "ana"), ("dee", "restored", "Jug", "ana")]


def test_nobody_hears_about_a_page_nobody_watched(wiki) -> None:
    kitchen(wiki)
    wiki.purge_page(wiki.delete_page("Kettle", "ana"), "ana")
    assert wiki.outbox() == []


def test_maintenance_purges_in_its_own_name() -> None:
    clock = ManualClock()
    wiki = Wiki.memory(clock=clock)
    stocked(wiki)
    wiki.delete_page("Kettle", "ana")
    wiki.drain_outbox()
    clock.advance(days=31)
    assert wiki.maintain().trash_purged == 1
    assert events(wiki) == [
        ("cy", "purged", "Kettle", "maintenance"),
        ("dee", "purged", "Kettle", "maintenance"),
    ]
    (change,) = wiki.recent_changes(limit=1)
    assert (change.kind, change.title, change.author) == ("purge", "Kettle", "maintenance")
