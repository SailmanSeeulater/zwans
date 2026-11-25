import pytest
from conftest import kitchen
from leafwiki.errors import InvalidSetting


def test_nothing_to_do_on_a_fresh_wiki(wiki) -> None:
    kitchen(wiki)
    assert wiki.maintain().total == 0


def test_old_revisions_are_pruned_when_asked(wiki) -> None:
    kitchen(wiki)
    for n in range(5):
        wiki.edit_page("Kettle", f"version {n}")
    wiki.set_setting("keep_revisions", 2)
    report = wiki.maintain()
    assert report.revisions_pruned == 4
    assert [r.number for r in wiki.history("Kettle")] == [5, 6]
    assert [r.number for r in wiki.history("Teapot")] == [1]


def test_old_changes_are_trimmed(wiki, clock) -> None:
    kitchen(wiki)
    clock.advance(days=100)
    wiki.edit_page("Kettle", "fresh")
    report = wiki.maintain()
    assert report.changes_trimmed == 3
    assert [c.kind for c in wiki.recent_changes()] == ["edit"]


def test_the_outbox_is_capped(wiki) -> None:
    kitchen(wiki)
    wiki.watch("Kettle", "cy")
    for n in range(5):
        wiki.edit_page("Kettle", f"v{n}", "bo")
    wiki.set_setting("outbox_limit", 2)
    assert wiki.maintain().outbox_dropped == 3
    assert [m.event for m in wiki.outbox()] == ["edited", "edited"]


def test_unused_attachment_contents_are_removed(wiki) -> None:
    kitchen(wiki)
    wiki.attach("Kettle", "a.txt", b"one")
    wiki.attach("Teapot", "b.txt", b"two")
    wiki.attach("Teapot", "c.txt", b"one")
    wiki.detach("Kettle", "a.txt")
    wiki.detach("Teapot", "b.txt")
    report = wiki.maintain()
    assert report.blobs_removed == 1
    assert wiki.attachment("Teapot", "c.txt") == b"one"


def test_settings_are_checked(wiki) -> None:
    with pytest.raises(InvalidSetting):
        wiki.set_setting("keep_revisions", -1)
    with pytest.raises(InvalidSetting):
        wiki.set_setting("no_such_thing", 1)
    with pytest.raises(InvalidSetting):
        wiki.set_setting("base_url", "ftp://x")
    wiki.set_setting("keep_revisions", "3")
    assert wiki.settings.keep_revisions == 3
