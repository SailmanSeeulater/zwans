"""A merge is one undo step, and undoing it puts everything back."""

from conftest import clock, world
from orbit import Crm


def tables(crm) -> dict:
    document = crm.store.document()["tables"]
    return {name: rows for name, rows in document.items() if name != "outbox" and rows}


def ids_of(contacts) -> list[str]:
    return [c.id for c in contacts]


def test_one_undo_restores_the_data_exactly(crm) -> None:
    ids = world(crm)
    before = tables(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    assert crm.undo() == "merge contacts"
    assert tables(crm) == before


def test_b_and_its_id_come_back(crm) -> None:
    ids = world(crm)
    before_b = crm.contact(ids["b"])
    crm.merge_contacts(ids["a"], ids["b"])
    crm.undo()
    assert crm.contact(ids["b"]) == before_b
    assert crm.contact(ids["a"]).emails == ["ada@analytical.example"]
    assert [n.body for n in crm.notes(ids["b"])] == ["Collects punched cards"]
    assert crm.deal(ids["d1"]).contact_ids == [ids["b"], ids["charles"], ids["a"]]
    assert {e.contact_name for e in crm.timeline(ids["b"])} == {"Augusta King"}
    assert "merged" not in [e.kind for e in crm.timeline(ids["a"])]


def test_indexes_see_b_again(crm) -> None:
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    crm.undo()
    assert ids_of(crm.search("augusta")) == [ids["b"]]
    assert ids_of(crm.search("punched")) == [ids["b"]]
    assert crm.duplicates()[0] == (ids["a"], ids["b"])
    assert ids_of(crm.tagged("looms")) == [ids["b"]]
    assert ids_of(crm.find_by_email("countess@home.example")) == [ids["b"]]


def test_undo_goes_back_past_the_merge_one_step_at_a_time(crm) -> None:
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    crm.add_note(ids["a"], "After")
    assert crm.undo() == "add note"
    assert crm.contact(ids["b"]).id == ids["a"]
    assert crm.undo() == "merge contacts"
    assert crm.contact(ids["b"]).id == ids["b"]
    assert crm.undo() != "merge contacts"


def test_undo_of_a_merge_works_after_reopening(path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    crm.save()
    reopened = Crm.open(path, clock=clock())
    assert reopened.undo() == "merge contacts"
    assert reopened.contact(ids["b"]).first_name == "Augusta"
    assert ids_of(reopened.search("augusta")) == [ids["b"]]
    reopened.save()
    assert Crm.open(path).contact(ids["b"]).id == ids["b"]


def test_a_failed_merge_leaves_nothing_behind(crm) -> None:
    ids = world(crm)
    before = tables(crm)
    history = crm.history()
    try:
        crm.merge_contacts(ids["a"], "c99")
    except Exception:
        pass
    assert tables(crm) == before
    assert crm.history() == history
