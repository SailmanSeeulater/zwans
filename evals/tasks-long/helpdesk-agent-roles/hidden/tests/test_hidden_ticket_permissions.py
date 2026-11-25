"""Who may do what to a ticket, and what a refusal leaves behind."""

import pytest
from deskline import Desk
from deskline.clock import SteppingClock
from deskline.errors import PermissionDenied
from deskline.services import tickets
from conftest import staff


@pytest.fixture
def three(desk, ctx, people):
    """T-1 unassigned, T-2 assigned to ana, T-3 assigned to al."""
    t1 = tickets.create(ctx, people["jane"].id, "Printer", "It jams")
    t2 = tickets.create(ctx, people["jane"].id, "Scanner", "It scans badly")
    t3 = tickets.create(ctx, people["bob"].id, "Phone", "It rings")
    tickets.assign(ctx, t2.id, "ana")
    tickets.assign(ctx, t3.id, "al")
    return t1.id, t2.id, t3.id


def denied(fn, permission):
    with pytest.raises(PermissionDenied) as caught:
        fn()
    assert caught.value.permission == permission
    return caught.value


def test_viewers_only_look(desk, people, as_, three) -> None:
    t1, t2, _ = three
    vic = as_("vic")
    assert tickets.get(vic, t1).subject == "Printer"
    assert len(tickets.list_tickets(vic)) == 3
    denied(lambda: tickets.create(vic, people["jane"].id, "Hi", "Hello"), "ticket.create")
    denied(lambda: tickets.reply(vic, t1, "Hello"), "ticket.edit")
    denied(lambda: tickets.note(vic, t1, "Hmm"), "ticket.note")
    denied(lambda: tickets.set_status(vic, t1, "pending"), "ticket.edit")
    denied(lambda: tickets.add_tag(vic, t1, "x"), "ticket.edit")
    denied(lambda: tickets.take(vic, t1), "ticket.edit")


def test_agents_work_their_own_and_unassigned_tickets(desk, as_, three) -> None:
    t1, t2, _ = three
    ana = as_("ana")
    tickets.reply(ana, t1, "Looking into it")
    tickets.set_priority(ana, t1, "high")
    tickets.set_status(ana, t2, "pending")
    tickets.add_tag(ana, t2, "scanner")
    tickets.remove_tag(ana, t2, "scanner")
    tickets.set_queue(ana, t2, "billing")
    assert desk.store.tickets[t2].queue == "billing"


@pytest.mark.parametrize(
    "operation",
    [
        lambda c, t: tickets.reply(c, t, "Mine now"),
        lambda c, t: tickets.set_status(c, t, "pending"),
        lambda c, t: tickets.set_priority(c, t, "urgent"),
        lambda c, t: tickets.set_queue(c, t, "billing"),
        lambda c, t: tickets.add_tag(c, t, "meddling"),
        lambda c, t: tickets.remove_tag(c, t, "anything"),
    ],
)
def test_agents_keep_off_other_agents_tickets(desk, as_, three, operation) -> None:
    _, _, t3 = three
    before = desk.store.tickets[t3].to_dict()
    denied(lambda: operation(as_("ana"), t3), "ticket.edit")
    assert desk.store.tickets[t3].to_dict() == before
    operation(as_("lou"), t3)


def test_notes_go_on_any_ticket(desk, as_, three) -> None:
    _, _, t3 = three
    tickets.note(as_("ana"), t3, "Al, the customer called")
    assert desk.store.tickets[t3].comments[-1].public is False


def test_taking_and_assigning(desk, as_, three) -> None:
    t1, t2, t3 = three
    tickets.take(as_("ana"), t1)
    assert desk.store.tickets[t1].assignee == "ana"
    denied(lambda: tickets.take(as_("ana"), t3), "ticket.edit")
    denied(lambda: tickets.assign(as_("ana"), t2, "al"), "ticket.assign")
    denied(lambda: tickets.assign(as_("ana"), t2, None), "ticket.assign")
    tickets.assign(as_("ana"), t2, "ana")
    assert desk.store.tickets[t3].assignee == "al"
    assert desk.store.tickets[t2].assignee == "ana"
    tickets.assign(as_("lou"), t3, "ana")
    tickets.assign(as_("lou"), t2, None)
    assert desk.store.tickets[t3].assignee == "ana"
    assert desk.store.tickets[t2].assignee is None


def test_only_admins_delete(desk, as_, three) -> None:
    t1, _, _ = three
    denied(lambda: tickets.delete(as_("lou"), t1), "ticket.delete")
    assert t1 in desk.store.tickets
    tickets.delete(as_("ada"), t1)
    assert t1 not in desk.store.tickets


# -- the audit trail of a refusal -------------------------------------------------------


def test_a_refusal_is_audited(desk, as_, three) -> None:
    _, _, t3 = three
    with pytest.raises(PermissionDenied):
        tickets.reply(as_("ana"), t3, "Mine now")
    entry = desk.store.audit[-1]
    assert entry.action == "permission.denied"
    assert entry.actor == "ana"
    assert entry.target == t3
    assert entry.details["permission"] == "ticket.edit"
    assert not any(c.body == "Mine now" for c in desk.store.tickets[t3].comments)
    assert not [e for e in desk.store.audit if e.action == "ticket.replied" and e.target == t3]


def test_a_refused_read_is_audited_too(desk, as_, three) -> None:
    from deskline.export import csv_export

    with pytest.raises(PermissionDenied):
        csv_export.tickets_csv(as_("vic"))
    entry = desk.store.audit[-1]
    assert (entry.action, entry.actor, entry.details["permission"]) == (
        "permission.denied", "vic", "export",
    )


def test_refusals_are_saved_to_the_file(tmp_path) -> None:
    path = tmp_path / "desk.json"
    desk = Desk.create(path, SteppingClock())
    people = staff(desk)
    ticket = tickets.create(desk.system, people["jane"].id, "Printer", "It jams")
    tickets.assign(desk.system, ticket.id, "al")
    with pytest.raises(PermissionDenied):
        tickets.set_status(desk.context("ana"), ticket.id, "solved")
    with pytest.raises(PermissionDenied):
        tickets.delete(desk.context("vic"), ticket.id)

    again = Desk.open(path, SteppingClock())
    refusals = [e for e in again.store.audit if e.action == "permission.denied"]
    assert [(e.actor, e.target, e.details["permission"]) for e in refusals] == [
        ("ana", ticket.id, "ticket.edit"),
        ("vic", ticket.id, "ticket.delete"),
    ]
    assert again.store.tickets[ticket.id].status == "open"


def test_a_refusal_inside_a_larger_transaction_still_leaves_its_entry(desk, as_, three) -> None:
    t1, _, t3 = three
    ana = as_("ana")
    with pytest.raises(PermissionDenied):
        with desk.store.transaction():
            tickets.add_tag(ana, t1, "fine")
            tickets.add_tag(ana, t3, "not fine")
    assert desk.store.tickets[t1].tags == []
    assert desk.store.audit[-1].action == "permission.denied"
    assert desk.store.audit[-1].target == t3
