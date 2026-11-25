import pytest
from conftest import clock, seed
from orbit import Crm
from orbit.errors import NotFound, NothingToUndo


def test_undo_reverts_the_last_change(crm) -> None:
    ids = seed(crm)
    crm.update_contact(ids["ada"], last_name="King")
    assert crm.undo() == "update contact"
    assert crm.contact(ids["ada"]).last_name == "Lovelace"
    assert {e.contact_name for e in crm.timeline(ids["ada"])} == {"Ada Lovelace"}


def test_undo_goes_back_one_change_at_a_time(crm) -> None:
    ids = seed(crm)
    crm.move_deal(ids["engine"], "proposal")
    crm.add_note(ids["grace"], "Hello")
    assert crm.undo() == "add note"
    assert crm.notes(ids["grace"]) == []
    assert crm.undo() == "move deal"
    assert crm.deal(ids["engine"]).stage == "qualified"
    assert [h["label"] for h in crm.history()][:2] == ["move deal", "add deal"]


def test_undoing_a_new_contact_removes_it_everywhere(crm) -> None:
    seed(crm)
    twin = crm.add_contact("Grace", "Hopper", emails=["gh@example.com"], tags=["twin"])
    assert crm.duplicates()
    crm.undo()
    with pytest.raises(NotFound):
        crm.contact(twin.id)
    assert crm.search("gh") == []
    assert crm.duplicates() == []
    assert crm.tagged("twin") == []
    assert crm.timeline(twin.id) == []


def test_undo_sends_no_webhooks_and_keeps_the_outbox(crm) -> None:
    crm.subscribe("https://hooks.example/all")
    ids = seed(crm)
    before = len(crm.outbox())
    crm.add_note(ids["ada"], "One more")
    crm.undo()
    assert len(crm.outbox()) == before + 1


def test_nothing_to_undo(crm) -> None:
    with pytest.raises(NothingToUndo):
        crm.undo()


def test_a_failed_change_leaves_nothing_behind(crm) -> None:
    ids = seed(crm)
    with pytest.raises(NotFound):
        with crm.operation("two notes"):
            crm.activities.add_note(ids["ada"], "First half")
            crm.activities.add_note("c99", "Second half")
    assert len(crm.notes(ids["ada"])) == 1
    assert crm.search("half") == []
    assert crm.history()[0]["label"] == "move deal"


def test_undo_history_is_saved_with_the_data(path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = seed(crm)
    crm.add_note(ids["grace"], "Saved note")
    crm.save()
    reopened = Crm.open(path, clock=clock())
    assert reopened.undo() == "add note"
    assert reopened.notes(ids["grace"]) == []
    assert reopened.search("saved") == []


def test_undo_keeps_a_limited_history(crm) -> None:
    from orbit.config import Settings

    small = Crm.memory(clock=clock(), settings=Settings(undo_limit=3))
    for number in range(5):
        small.add_contact(f"Person {number}")
    for _ in range(3):
        small.undo()
    with pytest.raises(NothingToUndo):
        small.undo()
    assert [c.first_name for c in small.list_contacts()] == ["Person 0", "Person 1"]
    assert crm is not small
