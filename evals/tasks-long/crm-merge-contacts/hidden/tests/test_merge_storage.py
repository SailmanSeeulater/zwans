"""Merges survive saving, reopening, backups and restores; old files can be merged in."""

import json

from conftest import clock, world
from orbit import Crm
from orbit.store import backup


def test_a_merge_survives_saving_and_reopening(path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    crm.save()
    assert json.loads(path.read_text())["version"] == 2
    reopened = Crm.open(path, clock=clock())
    assert reopened.contact(ids["b"]).id == ids["a"]
    assert [c.id for c in reopened.list_contacts()] == [
        ids["a"],
        ids["charles"],
        ids["grace"],
        ids["twin"],
    ]
    assert reopened.timeline(ids["b"]) == crm.timeline(ids["a"])


def test_ids_are_not_reused_after_reopening(path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = world(crm)
    crm.merge_contacts(ids["grace"], ids["twin"])  # the newest contact
    crm.save()
    reopened = Crm.open(path, clock=clock())
    fresh = reopened.add_contact("Alan", "Turing")
    assert fresh.id != ids["twin"]
    assert reopened.contact(ids["twin"]).id == ids["grace"]


def test_a_merge_survives_backup_and_restore(path, tmp_path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    crm.save()
    saved = backup.create_backup(crm.store, tmp_path / "backups", clock())
    crm.add_contact("Later", "Addition")
    backup.restore(saved, crm.store)
    crm.rebuild_indexes()
    assert crm.contact(ids["b"]).id == ids["a"]
    assert crm.add_note(ids["b"], "Restored").contact_id == ids["a"]
    assert crm.search("augusta") == []
    crm.save()
    assert Crm.open(path).contact(ids["b"]).id == ids["a"]


def test_contacts_from_an_old_file_can_be_merged(v1_file) -> None:
    crm = Crm.open(v1_file, clock=clock())
    assert crm.duplicates() == [("c1", "c3")]
    merged = crm.merge_contacts("c1", "c3")
    assert merged.emails == ["grace@navy.example", "ghopper@cobol.example"]
    assert merged.phones == ["+1 202 555 0143", "202-555-0143"]
    assert crm.duplicates() == []
    assert [n.id for n in crm.notes("c1")] == ["n1", "n2"]
    assert crm.deal("d3").contact_ids == ["c1"]
    assert [t.contact_id for t in crm.tasks()] == ["c1"]
    assert {e.contact_id for e in crm.timeline("c3")} == {"c1"}
    crm.save()
    reopened = Crm.open(v1_file, clock=clock())
    assert reopened.contact("c3").id == "c1"
    assert reopened.add_contact("Mary", "Jackson").id not in ("c1", "c2", "c3", "c4")


def test_merging_the_newest_contact_of_an_old_file(v1_file) -> None:
    crm = Crm.open(v1_file, clock=clock())
    crm.merge_contacts("c2", "c4")
    mary = crm.add_contact("Mary", "Jackson")
    assert mary.id != "c4"
    assert crm.contact("c4").id == "c2"
    assert crm.contact(mary.id).first_name == "Mary"
