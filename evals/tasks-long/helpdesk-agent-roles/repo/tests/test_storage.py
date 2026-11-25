import json

import pytest
from deskline import Desk
from deskline.clock import SteppingClock
from deskline.errors import StoreError
from deskline.export import backup
from deskline.services import customers, tickets
from conftest import seed


def test_changes_are_saved_and_read_back(tmp_path) -> None:
    path = tmp_path / "desk.json"
    desk = Desk.create(path, SteppingClock())
    people = seed(desk)
    ticket = tickets.create(desk.system, people["jane"].id, "Printer", "It jams", tags=["hw"])
    tickets.assign(desk.system, ticket.id, "maria")

    again = Desk.open(path, SteppingClock())
    loaded = again.store.tickets[ticket.id]
    assert loaded.assignee == "maria"
    assert loaded.tags == ["hw"]
    assert loaded.comments[0].body == "It jams"
    assert again.store.customers[people["jane"].id].address == "12 Elm Street, Springfield"
    assert again.store.agents["maria"].teams == ["money"]
    assert [e.action for e in again.store.audit] == [e.action for e in desk.store.audit]
    document = json.loads(path.read_text())
    assert document["format"] == "deskline"


def test_a_version_1_file_is_upgraded(legacy_file) -> None:
    desk = Desk.open(legacy_file, SteppingClock())
    jane = desk.store.customers["C-1"]
    assert (jane.email, jane.phone) == ("jane@example.org", "+1 555 0101")
    assert desk.store.customers["C-2"].phone == "+44 20 7946 0000"
    assert desk.store.tickets["T-1"].assignee == "maria"
    assert desk.store.tickets["T-2"].assignee is None
    assert desk.store.tickets["T-1"].tags == ["login", "web"]
    assert desk.store.agents["otto"].active is False
    created = customers.create(desk.system, "New One")
    assert created.id == "C-3"


def test_the_upgraded_file_keeps_working(legacy_file) -> None:
    desk = Desk.open(legacy_file, SteppingClock())
    tickets.reply(desk.context("maria"), "T-1", "Try again now")
    again = Desk.open(legacy_file, SteppingClock())
    assert again.store.tickets["T-1"].comments[-1].body == "Try again now"


def test_a_newer_file_is_refused(tmp_path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"format": "deskline", "version": 99, "data": {}}))
    with pytest.raises(StoreError):
        Desk.open(path)


def test_backup_and_restore_round_trip(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    document = backup.dump(ctx)
    tickets.delete(ctx, ticket.id)
    customers.update(ctx, seeded["jane"].id, phone="000")
    counts = backup.restore(ctx, json.loads(json.dumps(document)))
    assert counts == {"tickets": 1, "customers": 2}
    assert desk.store.tickets[ticket.id].subject == "Printer"
    assert desk.store.customers[seeded["jane"].id].phone == "+1 555 0101"
    assert desk.store.audit[-1].action == "desk.restored"
