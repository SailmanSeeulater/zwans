import pytest
from deskline.errors import Conflict, NotFound, ValidationError
from deskline.services import bulk, macros, merging, searches, tickets


def test_a_macro_applies_all_its_actions(desk, ctx, seeded) -> None:
    macro = macros.create_macro(
        ctx,
        "Need more info",
        [
            {"type": "reply", "value": "Hello {{ customer.name }}, could you tell us more?"},
            {"type": "set_status", "value": "pending"},
            {"type": "add_tag", "value": "waiting"},
        ],
    )
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    maria = desk.context("maria")
    tickets.take(maria, ticket.id)
    macros.apply_macro(maria, macro.id, ticket.id)
    assert ticket.status == "pending"
    assert ticket.tags == ["waiting"]
    assert ticket.comments[-1].body == "Hello Jane Doe, could you tell us more?"
    assert ticket.comments[-1].via == "macro"


def test_a_failing_macro_changes_nothing(desk, ctx, seeded) -> None:
    macro = macros.create_macro(
        ctx,
        "Close it",
        [{"type": "add_tag", "value": "done"}, {"type": "set_status", "value": "closed"}],
    )
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    with pytest.raises(Conflict):
        macros.apply_macro(ctx, macro.id, ticket.id)
    assert desk.store.tickets[ticket.id].tags == []


def test_macro_actions_are_validated(ctx, seeded) -> None:
    with pytest.raises(ValidationError):
        macros.create_macro(ctx, "Bad", [{"type": "explode", "value": "now"}])
    with pytest.raises(ValidationError):
        macros.create_macro(ctx, "Bad", [{"type": "set_priority", "value": "whenever"}])


def test_bulk_updates_are_all_or_nothing(desk, ctx, seeded) -> None:
    a = tickets.create(ctx, seeded["jane"].id, "One", "first")
    b = tickets.create(ctx, seeded["bob"].id, "Two", "second")
    changed = bulk.bulk_update(ctx, [a.id, b.id], {"priority": "high", "add_tags": ["batch"]})
    assert [t.priority for t in changed] == ["high", "high"]
    tickets.set_status(ctx, b.id, "solved")
    tickets.set_status(ctx, b.id, "closed")
    with pytest.raises(Conflict):
        bulk.bulk_update(ctx, [a.id, b.id], {"assignee": "maria"})
    assert desk.store.tickets[a.id].assignee is None


def test_merging_moves_the_conversation(desk, ctx, seeded) -> None:
    a = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams", tags=["hardware"])
    b = tickets.create(ctx, seeded["jane"].id, "Printer again", "Still jams")
    target = merging.merge(ctx, b.id, a.id)
    assert target.id == a.id
    assert b.status == "closed"
    assert b.merged_into == a.id
    bodies = [c.body for c in a.comments]
    assert "Still jams" in bodies
    assert bodies[-1].startswith(f"Merged {b.id}")
    with pytest.raises(Conflict):
        merging.merge(ctx, b.id, a.id)


def test_saved_searches_are_private_unless_shared(desk, ctx, seeded) -> None:
    tickets.create(ctx, seeded["jane"].id, "Printer", "It jams", priority="high")
    tickets.create(ctx, seeded["bob"].id, "Refund", "Refund me")
    maria, tom = desk.context("maria"), desk.context("tom")
    mine = searches.save_search(maria, "Hot", "priority:high")
    assert [s.id for s in searches.list_searches(tom)] == []
    result = searches.run_saved(maria, mine.id)
    assert result["count"] == 1
    assert result["results"][0]["subject"] == "Printer"
    with pytest.raises(NotFound):
        searches.run_saved(tom, mine.id)
    searches.delete_search(maria, mine.id)
    assert searches.list_searches(maria) == []


def test_assignee_me_means_whoever_runs_the_search(desk, ctx, seeded) -> None:
    a = tickets.create(ctx, seeded["jane"].id, "One", "first")
    b = tickets.create(ctx, seeded["bob"].id, "Two", "second")
    tickets.take(desk.context("maria"), a.id)
    tickets.take(desk.context("tom"), b.id)
    shared = searches.save_search(ctx, "Mine", "assignee:me", shared=True)
    assert [r["id"] for r in searches.run_saved(desk.context("maria"), shared.id)["results"]] == [a.id]
    assert [r["id"] for r in searches.run_saved(desk.context("tom"), shared.id)["results"]] == [b.id]
