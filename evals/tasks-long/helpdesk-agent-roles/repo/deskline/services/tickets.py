"""Tickets: creating them, talking on them, and moving them through the workflow.

The functions taking a ticket id are the operations callers use; each runs in its own
transaction. The ``change_*``/``post_*`` helpers below them work on a ticket that is
already loaded, inside a transaction the caller holds; macros, bulk updates, merging and
the mail gateway build on them.
"""

from __future__ import annotations

from .. import notify
from ..context import Context
from ..errors import Conflict, InvalidTransition, ValidationError
from ..models import PRIORITIES, STATUSES, TRANSITIONS, Comment, Ticket
from ..textutil import parse_tags
from . import queues, sla


def _touch(ctx: Context, ticket: Ticket) -> str:
    now = ctx.now()
    ticket.updated_at = now
    return now


def _check_agent(ctx: Context, agent_id: str) -> None:
    agent = ctx.store.agent(agent_id)
    if not agent.active:
        raise ValidationError(f"agent {agent_id} is not active")


# -- creating ---------------------------------------------------------------------------


def create(
    ctx: Context,
    customer_id: str,
    subject: str,
    body: str,
    *,
    priority: str | None = None,
    queue: str | None = None,
    tags: list[str] | tuple[str, ...] = (),
    via: str = "web",
    from_address: str = "",
    acknowledge: bool = True,
) -> Ticket:
    subject = " ".join(subject.split())
    if not subject:
        raise ValidationError("a ticket needs a subject")
    if not body.strip():
        raise ValidationError("a ticket needs a message")
    if priority is not None and priority not in PRIORITIES:
        raise ValidationError(f"unknown priority {priority!r}")
    with ctx.store.transaction():
        customer = ctx.store.customer(customer_id)
        if queue is None:
            queue = queues.route(ctx.store, f"{subject} {body}") or ctx.setting("default_queue")
        queues.ensure_default(ctx.store, ctx.setting("default_queue"))
        target_queue = ctx.store.queue(queue)
        now = ctx.now()
        ticket = Ticket(
            id=ctx.store.next_id("ticket", "T"),
            subject=subject,
            customer_id=customer.id,
            priority=priority or target_queue.default_priority,
            queue=target_queue.id,
            tags=parse_tags(",".join(tags)),
            created_at=now,
            updated_at=now,
        )
        ticket.comments.append(
            Comment(
                id=1,
                author_kind="customer",
                author=customer.id,
                body=body.strip(),
                public=True,
                created_at=now,
                via=via,
                from_address=from_address,
            )
        )
        sla.apply_targets(ctx.store, ticket)
        ctx.store.tickets[ticket.id] = ticket
        details = {
            "subject": subject,
            "customer": customer.id,
            "queue": ticket.queue,
            "priority": ticket.priority,
            "via": via,
        }
        if from_address:
            details["from_address"] = from_address
        ctx.record("ticket.created", ticket.id, **details)
        notify.ticket_created(ctx, ticket, acknowledge=acknowledge)
    return ticket


# -- reading ----------------------------------------------------------------------------


def get(ctx: Context, ticket_id: str) -> Ticket:
    return ctx.store.ticket(ticket_id)


def list_tickets(
    ctx: Context,
    *,
    status: str | None = None,
    queue: str | None = None,
    assignee: str | None = None,
    customer: str | None = None,
) -> list[Ticket]:
    out = []
    for ticket in ctx.store.tickets.values():
        if status is not None and ticket.status != status:
            continue
        if queue is not None and ticket.queue != queue:
            continue
        if assignee is not None and (ticket.assignee or "") != assignee:
            continue
        if customer is not None and ticket.customer_id != customer:
            continue
        out.append(ticket)
    return sorted(out, key=lambda t: int(t.id.split("-")[1]))


# -- helpers on a loaded ticket ---------------------------------------------------------


def _author(ctx: Context) -> tuple[str, str]:
    return ("system", "system") if ctx.is_system else ("agent", ctx.actor_name)


def post_reply(ctx: Context, ticket: Ticket, body: str, *, via: str = "web") -> Comment:
    if not body.strip():
        raise ValidationError("a reply needs some text")
    if ticket.status == "closed":
        raise Conflict(f"{ticket.id} is closed")
    now = _touch(ctx, ticket)
    kind, author = _author(ctx)
    comment = Comment(ticket.next_comment_id(), kind, author, body.strip(), True, now, via)
    ticket.comments.append(comment)
    if kind == "agent" and ticket.first_response_at is None:
        ticket.first_response_at = now
    if ticket.status == "new":
        ticket.status = "open"
    ctx.record("ticket.replied", ticket.id, comment=comment.id, via=via)
    notify.agent_replied(ctx, ticket, comment)
    return comment


def post_note(ctx: Context, ticket: Ticket, body: str, *, via: str = "web") -> Comment:
    if not body.strip():
        raise ValidationError("a note needs some text")
    now = _touch(ctx, ticket)
    kind, author = _author(ctx)
    comment = Comment(ticket.next_comment_id(), kind, author, body.strip(), False, now, via)
    ticket.comments.append(comment)
    ctx.record("ticket.noted", ticket.id, comment=comment.id, via=via)
    return comment


def post_customer_comment(
    ctx: Context, ticket: Ticket, body: str, *, from_address: str = "", via: str = "email"
) -> Comment:
    now = _touch(ctx, ticket)
    comment = Comment(
        ticket.next_comment_id(),
        "customer",
        ticket.customer_id,
        body.strip(),
        True,
        now,
        via,
        from_address,
    )
    ticket.comments.append(comment)
    if ticket.status in ("pending", "solved"):
        if ticket.status == "solved":
            ticket.solved_at = None
        ticket.status = "open"
    ctx.record("ticket.customer_replied", ticket.id, comment=comment.id, from_address=from_address)
    notify.customer_replied(ctx, ticket, comment)
    return comment


def change_status(ctx: Context, ticket: Ticket, status: str) -> None:
    if status not in STATUSES:
        raise ValidationError(f"unknown status {status!r}")
    if status == ticket.status:
        return
    if status not in TRANSITIONS[ticket.status]:
        raise InvalidTransition(ticket.id, ticket.status, status)
    old = ticket.status
    now = _touch(ctx, ticket)
    ticket.status = status
    if status == "solved":
        ticket.solved_at = now
    elif status == "closed":
        ticket.closed_at = now
    elif old == "solved":
        ticket.solved_at = None
    ctx.record("ticket.status_changed", ticket.id, **{"from": old, "to": status})
    if status == "solved":
        from . import surveys

        surveys.on_solved(ctx, ticket)


def change_priority(ctx: Context, ticket: Ticket, priority: str) -> None:
    if priority not in PRIORITIES:
        raise ValidationError(f"unknown priority {priority!r}")
    if priority == ticket.priority:
        return
    old = ticket.priority
    _touch(ctx, ticket)
    ticket.priority = priority
    sla.apply_targets(ctx.store, ticket)
    ctx.record("ticket.priority_changed", ticket.id, **{"from": old, "to": priority})


def change_queue(ctx: Context, ticket: Ticket, queue_id: str) -> None:
    queue = ctx.store.queue(queue_id)
    if queue.id == ticket.queue:
        return
    old = ticket.queue
    _touch(ctx, ticket)
    ticket.queue = queue.id
    ctx.record("ticket.queue_changed", ticket.id, **{"from": old, "to": queue.id})


def tag(ctx: Context, ticket: Ticket, name: str) -> None:
    for tag_name in parse_tags(name):
        if tag_name not in ticket.tags:
            _touch(ctx, ticket)
            ticket.tags.append(tag_name)
            ctx.record("ticket.tagged", ticket.id, tag=tag_name)


def untag(ctx: Context, ticket: Ticket, name: str) -> None:
    for tag_name in parse_tags(name):
        if tag_name in ticket.tags:
            _touch(ctx, ticket)
            ticket.tags.remove(tag_name)
            ctx.record("ticket.untagged", ticket.id, tag=tag_name)


def change_assignee(ctx: Context, ticket: Ticket, agent_id: str | None) -> None:
    if agent_id is not None:
        _check_agent(ctx, agent_id)
    if agent_id == ticket.assignee:
        return
    if ticket.status == "closed":
        raise Conflict(f"{ticket.id} is closed")
    old = ticket.assignee
    _touch(ctx, ticket)
    ticket.assignee = agent_id
    if agent_id is not None and ticket.status == "new":
        ticket.status = "open"
    ctx.record("ticket.assigned", ticket.id, **{"from": old, "to": agent_id})
    notify.ticket_assigned(ctx, ticket)


# -- operations -------------------------------------------------------------------------


def reply(ctx: Context, ticket_id: str, body: str, *, via: str = "web") -> Comment:
    with ctx.store.transaction():
        return post_reply(ctx, ctx.store.ticket(ticket_id), body, via=via)


def note(ctx: Context, ticket_id: str, body: str, *, via: str = "web") -> Comment:
    with ctx.store.transaction():
        return post_note(ctx, ctx.store.ticket(ticket_id), body, via=via)


def set_status(ctx: Context, ticket_id: str, status: str) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        change_status(ctx, ticket, status)
    return ticket


def set_priority(ctx: Context, ticket_id: str, priority: str) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        change_priority(ctx, ticket, priority)
    return ticket


def set_queue(ctx: Context, ticket_id: str, queue_id: str) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        change_queue(ctx, ticket, queue_id)
    return ticket


def add_tag(ctx: Context, ticket_id: str, name: str) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        tag(ctx, ticket, name)
    return ticket


def remove_tag(ctx: Context, ticket_id: str, name: str) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        untag(ctx, ticket, name)
    return ticket


def assign(ctx: Context, ticket_id: str, agent_id: str | None) -> Ticket:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        change_assignee(ctx, ticket, agent_id)
    return ticket


def take(ctx: Context, ticket_id: str) -> Ticket:
    if ctx.is_system:
        raise ValidationError("the system cannot take tickets")
    return assign(ctx, ticket_id, ctx.actor)


def delete(ctx: Context, ticket_id: str) -> None:
    with ctx.store.transaction():
        ticket = ctx.store.ticket(ticket_id)
        del ctx.store.tickets[ticket.id]
        for survey_id in [s.id for s in ctx.store.surveys.values() if s.ticket_id == ticket.id]:
            del ctx.store.surveys[survey_id]
        ctx.record("ticket.deleted", ticket.id, subject=ticket.subject)


def close_solved(ctx: Context, older_than_days: float) -> list[str]:
    """Close solved tickets nobody has touched for a while (the auto-close job)."""
    from ..clock import days_between

    closed = []
    with ctx.store.transaction():
        now = ctx.now()
        for ticket in list_tickets(ctx, status="solved"):
            if ticket.solved_at and days_between(ticket.solved_at, now) >= older_than_days:
                change_status(ctx, ticket, "closed")
                closed.append(ticket.id)
    return closed
