"""Operations that do several things: macros, bulk updates, merging."""

import pytest
from deskline.errors import PermissionDenied
from deskline.services import bulk, macros, merging, tickets


@pytest.fixture
def three(desk, ctx, people):
    """T-1 unassigned, T-2 assigned to ana, T-3 assigned to al."""
    t1 = tickets.create(ctx, people["jane"].id, "Printer", "It jams")
    t2 = tickets.create(ctx, people["jane"].id, "Scanner", "It scans badly")
    t3 = tickets.create(ctx, people["bob"].id, "Phone", "It rings")
    tickets.assign(ctx, t2.id, "ana")
    tickets.assign(ctx, t3.id, "al")
    return t1.id, t2.id, t3.id


def snapshot(desk) -> dict:
    data = desk.store.to_data()
    data.pop("audit")
    return data


# -- macros -----------------------------------------------------------------------------


def test_managing_macros_is_for_leads(desk, as_, people) -> None:
    actions = [{"type": "set_status", "value": "pending"}]
    with pytest.raises(PermissionDenied) as caught:
        macros.create_macro(as_("ana"), "Hold", actions)
    assert caught.value.permission == "macro.manage"
    macro = macros.create_macro(as_("lou"), "Hold", actions)
    with pytest.raises(PermissionDenied):
        macros.update_macro(as_("al"), macro.id, name="Wait")
    with pytest.raises(PermissionDenied):
        macros.delete_macro(as_("al"), macro.id)
    assert [m.name for m in macros.list_macros(as_("vic"))] == ["Hold"]


def test_viewers_cannot_run_macros(desk, ctx, as_, three) -> None:
    t1, _, _ = three
    macro = macros.create_macro(ctx, "Note", [{"type": "note", "value": "seen"}])
    with pytest.raises(PermissionDenied):
        macros.apply_macro(as_("vic"), macro.id, t1)
    assert len(desk.store.tickets[t1].comments) == 1


def test_every_macro_action_is_checked(desk, ctx, as_, three) -> None:
    """A macro may not do what its user could not do by hand: here, hand a ticket to al."""
    _, t2, _ = three
    macro = macros.create_macro(
        ctx,
        "Escalate to Al",
        [
            {"type": "reply", "value": "Passing you to Al."},
            {"type": "add_tag", "value": "escalated"},
            {"type": "assign", "value": "al"},
        ],
    )
    before = snapshot(desk)
    with pytest.raises(PermissionDenied) as caught:
        macros.apply_macro(as_("ana"), macro.id, t2)
    assert caught.value.permission == "ticket.assign"
    assert snapshot(desk) == before
    assert desk.store.audit[-1].action == "permission.denied"
    macros.apply_macro(as_("lou"), macro.id, t2)
    assert desk.store.tickets[t2].assignee == "al"


def test_a_macro_on_someone_elses_ticket(desk, ctx, as_, three) -> None:
    _, _, t3 = three
    note_only = macros.create_macro(ctx, "Remark", [{"type": "note", "value": "FYI {{ customer.name }}"}])
    hold = macros.create_macro(
        ctx, "Hold", [{"type": "note", "value": "Holding"}, {"type": "set_status", "value": "pending"}]
    )
    macros.apply_macro(as_("ana"), note_only.id, t3)
    assert desk.store.tickets[t3].comments[-1].body == "FYI Bob Stone"
    before = snapshot(desk)
    with pytest.raises(PermissionDenied) as caught:
        macros.apply_macro(as_("ana"), hold.id, t3)
    assert caught.value.permission == "ticket.edit"
    assert snapshot(desk) == before


def test_assign_self_in_a_macro_is_taking(desk, ctx, as_, three) -> None:
    t1, _, t3 = three
    grab = macros.create_macro(
        ctx, "Grab", [{"type": "assign_self"}, {"type": "set_status", "value": "pending"}]
    )
    macros.apply_macro(as_("ana"), grab.id, t1)
    assert desk.store.tickets[t1].assignee == "ana"
    assert desk.store.tickets[t1].status == "pending"
    with pytest.raises(PermissionDenied):
        macros.apply_macro(as_("ana"), grab.id, t3)
    assert desk.store.tickets[t3].assignee == "al"
    to_ana = macros.create_macro(ctx, "To Ana", [{"type": "assign", "value": "ana"}])
    tickets.assign(ctx, t1, None)
    macros.apply_macro(as_("ana"), to_ana.id, t1)
    assert desk.store.tickets[t1].assignee == "ana"


# -- bulk updates -----------------------------------------------------------------------


def test_bulk_checks_every_ticket(desk, as_, three) -> None:
    t1, t2, t3 = three
    before = snapshot(desk)
    with pytest.raises(PermissionDenied) as caught:
        bulk.bulk_update(as_("ana"), [t1, t2, t3], {"priority": "high", "add_tags": ["sweep"]})
    assert caught.value.permission == "ticket.edit"
    assert snapshot(desk) == before
    assert desk.store.audit[-1].target == t3
    bulk.bulk_update(as_("ana"), [t1, t2], {"priority": "high"})
    assert [desk.store.tickets[t].priority for t in (t1, t2, t3)] == ["high", "high", "normal"]


def test_bulk_assigning_needs_ticket_assign(desk, as_, three) -> None:
    t1, t2, _ = three
    with pytest.raises(PermissionDenied) as caught:
        bulk.bulk_update(as_("ana"), [t1, t2], {"assignee": "al"})
    assert caught.value.permission == "ticket.assign"
    assert desk.store.tickets[t1].assignee is None
    bulk.bulk_update(as_("ana"), [t1, t2], {"assignee": "ana"})
    assert desk.store.tickets[t1].assignee == "ana"
    with pytest.raises(PermissionDenied):
        bulk.bulk_update(as_("ana"), [t1], {"assignee": ""})
    bulk.bulk_update(as_("lou"), [t1, t2], {"assignee": "al", "status": "pending"})
    assert desk.store.tickets[t2].assignee == "al"


def test_viewers_cannot_bulk_update(desk, as_, three) -> None:
    t1, _, _ = three
    with pytest.raises(PermissionDenied):
        bulk.bulk_update(as_("vic"), [t1], {"add_tags": ["x"]})


# -- merging ----------------------------------------------------------------------------


def test_merging_needs_both_tickets(desk, as_, three) -> None:
    t1, t2, t3 = three
    before = snapshot(desk)
    with pytest.raises(PermissionDenied) as caught:
        merging.merge(as_("ana"), t3, t2)
    assert caught.value.permission == "ticket.edit"
    assert snapshot(desk) == before
    with pytest.raises(PermissionDenied):
        merging.merge(as_("ana"), t2, t3)
    assert snapshot(desk) == before
    assert desk.store.audit[-1].action == "permission.denied"
    merging.merge(as_("ana"), t1, t2)
    assert desk.store.tickets[t1].merged_into == t2


def test_leads_merge_anything_and_viewers_nothing(desk, as_, three) -> None:
    t1, t2, t3 = three
    with pytest.raises(PermissionDenied):
        merging.merge(as_("vic"), t1, t2)
    merging.merge(as_("lou"), t3, t2)
    assert desk.store.tickets[t3].merged_into == t2
