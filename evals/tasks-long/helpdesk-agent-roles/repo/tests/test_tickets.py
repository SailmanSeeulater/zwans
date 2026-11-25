import pytest
from deskline import auditview
from deskline.clock import add_minutes
from deskline.errors import Conflict, InvalidTransition, NotFound, ValidationError
from deskline.services import agents, tickets


def test_a_new_ticket_is_routed_by_keyword(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Wrong invoice", "The invoice is wrong.")
    assert ticket.id == "T-1"
    assert ticket.queue == "billing"
    assert ticket.status == "new"
    assert ticket.comments[0].author_kind == "customer"
    other = tickets.create(ctx, seeded["bob"].id, "Hello", "Just saying hi")
    assert other.queue == "general"


def test_sla_targets_follow_the_priority(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Down", "All down", priority="urgent")
    assert ticket.due_first_response == add_minutes(ticket.created_at, 30)
    assert ticket.due_resolution == add_minutes(ticket.created_at, 240)
    tickets.set_priority(ctx, ticket.id, "low")
    assert ticket.due_first_response == add_minutes(ticket.created_at, 480)
    assert ticket.due_resolution == add_minutes(ticket.created_at, 2880)


def test_the_first_agent_reply_opens_and_counts_as_first_response(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    maria = desk.context("maria")
    tickets.take(maria, ticket.id)
    tickets.reply(maria, ticket.id, "Please send a photo")
    assert ticket.status == "open"
    assert ticket.assignee == "maria"
    assert ticket.first_response_at is not None
    assert ticket.comments[-1].author == "maria"


def test_notes_are_internal(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.note(desk.context("tom"), ticket.id, "Probably the tray")
    assert ticket.comments[-1].public is False
    assert ticket.first_response_at is None
    assert [c.id for c in ticket.public_comments()] == [1]


def test_status_transitions_are_enforced(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.set_status(ctx, ticket.id, "pending")
    tickets.set_status(ctx, ticket.id, "solved")
    assert ticket.solved_at is not None
    tickets.set_status(ctx, ticket.id, "closed")
    with pytest.raises(InvalidTransition):
        tickets.set_status(ctx, ticket.id, "open")
    with pytest.raises(ValidationError):
        tickets.set_status(ctx, ticket.id, "sleeping")


def test_tags_and_queue_changes(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.add_tag(ctx, ticket.id, "Hardware, urgent")
    tickets.remove_tag(ctx, ticket.id, "urgent")
    tickets.set_queue(ctx, ticket.id, "billing")
    assert ticket.tags == ["hardware"]
    assert ticket.queue == "billing"
    with pytest.raises(NotFound):
        tickets.set_queue(ctx, ticket.id, "nowhere")


def test_assigning_needs_an_active_agent(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    agents.set_active(ctx, "tom", False)
    with pytest.raises(ValidationError):
        tickets.assign(ctx, ticket.id, "tom")
    ticket = tickets.assign(ctx, ticket.id, "maria")
    assert ticket.status == "open"
    tickets.assign(ctx, ticket.id, None)
    assert ticket.assignee is None


def test_deactivating_an_agent_releases_their_tickets(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.assign(ctx, ticket.id, "tom")
    agents.set_active(ctx, "tom", False)
    assert ticket.assignee is None


def test_replying_to_a_closed_ticket_is_refused(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.set_status(ctx, ticket.id, "solved")
    tickets.set_status(ctx, ticket.id, "closed")
    with pytest.raises(Conflict):
        tickets.reply(ctx, ticket.id, "Hello?")


def test_a_failed_change_leaves_nothing_behind(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    entries = len(desk.store.audit)
    with pytest.raises(NotFound):
        with desk.store.transaction():
            tickets.add_tag(ctx, ticket.id, "kept?")
            tickets.set_queue(ctx, ticket.id, "nowhere")
    assert desk.store.tickets[ticket.id].tags == []
    assert len(desk.store.audit) == entries


def test_every_change_is_audited_with_its_actor(desk, ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    maria = desk.context("maria")
    tickets.take(maria, ticket.id)
    tickets.set_priority(maria, ticket.id, "high")
    rows = auditview.history(ctx, ticket.id)
    assert [(r["actor"], r["action"]) for r in rows] == [
        ("system", "ticket.created"),
        ("maria", "ticket.assigned"),
        ("maria", "ticket.priority_changed"),
    ]
    assert rows[2]["details"] == {"from": "normal", "to": "high"}


def test_deleting_a_ticket(ctx, seeded) -> None:
    ticket = tickets.create(ctx, seeded["jane"].id, "Printer", "It jams")
    tickets.delete(ctx, ticket.id)
    with pytest.raises(NotFound):
        tickets.get(ctx, ticket.id)


def test_an_unknown_agent_has_no_context(desk) -> None:
    with pytest.raises(NotFound):
        desk.context("ghost")
