import json

import pytest
from conftest import clock, seed
from orbit import Crm
from orbit.errors import StoreError
from orbit.store import backup


def test_saving_and_reopening_keeps_everything(path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = seed(crm)
    crm.save()
    document = json.loads(path.read_text())
    assert document["version"] == 2
    reopened = Crm.open(path, clock=clock())
    assert reopened.contact(ids["ada"]) == crm.contact(ids["ada"])
    assert reopened.deal(ids["engine"]) == crm.deal(ids["engine"])
    assert [c.id for c in reopened.search("lovelace")] == [ids["ada"]]
    assert reopened.tag_counts() == {"vip": 1}


def test_a_missing_file_is_an_empty_crm(path) -> None:
    assert Crm.open(path).list_contacts() == []


def test_a_damaged_file_is_an_error(path) -> None:
    path.write_text("{not json")
    with pytest.raises(StoreError):
        Crm.open(path)
    path.write_text(json.dumps({"format": "orbit", "version": 9, "tables": {}}))
    with pytest.raises(StoreError):
        Crm.open(path)


def test_version_1_files_are_upgraded(v1_file) -> None:
    crm = Crm.open(v1_file, clock=clock())
    grace = crm.contact("c1")
    assert grace.emails == ["grace@navy.example"]
    assert grace.phones == ["+1 202 555 0143"]
    assert crm.contact("c4").emails == []
    assert crm.deal("d1").contact_ids == ["c1"]
    assert [c.stage for c in crm.deal("d1").history()] == ["lead", "proposal"]
    assert [e.kind for e in crm.timeline("c3")] == ["note"]
    assert crm.duplicates() == [("c1", "c3")]
    crm.add_note("c2", "Upgraded")
    crm.save()
    assert json.loads(v1_file.read_text())["version"] == 2
    assert Crm.open(v1_file).notes("c2")[0].body == "Upgraded"


def test_backup_and_restore(path, tmp_path) -> None:
    crm = Crm.open(path, clock=clock())
    ids = seed(crm)
    crm.save()
    saved = backup.create_backup(crm.store, tmp_path / "backups", clock())
    assert backup.list_backups(tmp_path / "backups") == [saved]
    crm.add_contact("Later", "Addition")
    counts = backup.restore(saved, crm.store)
    crm.rebuild_indexes()
    assert counts["contacts"] == 3
    assert [c.id for c in crm.list_contacts()] == [ids["ada"], ids["grace"], ids["charles"]]
    assert crm.search("addition") == []
    assert crm.history() == []


def test_a_damaged_backup_is_refused(path, tmp_path) -> None:
    crm = Crm.open(path, clock=clock())
    seed(crm)
    saved = backup.create_backup(crm.store, tmp_path, clock())
    wrapper = json.loads(saved.read_text())
    del wrapper["document"]["tables"]["deals"]["d1"]["stage"]
    saved.write_text(json.dumps(wrapper))
    with pytest.raises(StoreError):
        backup.restore(saved, crm.store)
    assert crm.deal("d1").stage == "qualified"
