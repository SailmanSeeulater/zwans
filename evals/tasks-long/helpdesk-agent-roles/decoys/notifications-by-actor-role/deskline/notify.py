"""Who hears about what.

Services call these after a change; each one renders a template and drops the mail in the
outbox. Agents never get mail about their own actions.
"""

from __future__ import annotations

from typing import Any

from .context import Context
from .mail import outbox, templates
from .models import Agent, Comment, Survey, Ticket
from .permissions import role_allows


def _queue_team_members(ctx: Context, ticket: Ticket) -> list[Agent]:
    queue = ctx.store.queues.get(ticket.queue)
    if queue is None or queue.team is None:
        return []
    team = ctx.store.teams.get(queue.team)
    if team is None:
        return []
    members = []
    for agent_id in team.members:
        agent = ctx.store.agents.get(agent_id)
        if agent is not None and agent.active and agent.id != ctx.actor:
            members.append(agent)
    return members


def _to_customer(
    ctx: Context, name: str, ticket: Ticket, *, comment: Comment | None = None, **extra: Any
) -> None:
    customer = ctx.store.customers.get(ticket.customer_id)
    if customer is None or not customer.email:
        return
    context = templates.ticket_context(ctx.store, ticket, comment=comment, extra=extra)
    subject, body = templates.render(name, context)
    outbox.queue_mail(
        ctx.store,
        ctx.now(),
        to=customer.email,
        subject=subject,
        body=body,
        template=name,
        ticket_id=ticket.id,
    )


def _to_agent(
    ctx: Context,
    agent: Agent,
    name: str,
    ticket: Ticket,
    *,
    comment: Comment | None = None,
    **extra: Any,
) -> None:
    if not agent.active or not agent.email or agent.id == ctx.actor:
        return
    hide = not role_allows(ctx.role, "contact.view")
    context = templates.ticket_context(
        ctx.store, ticket, comment=comment, extra=extra, hide=hide
    )
    context["recipient"] = {"id": agent.id, "name": agent.name}
    subject, body = templates.render(name, context)
    outbox.queue_mail(
        ctx.store,
        ctx.now(),
        to=agent.email,
        subject=subject,
        body=body,
        template=name,
        ticket_id=ticket.id,
        recipient_agent=agent.id,
    )


def ticket_created(ctx: Context, ticket: Ticket, *, acknowledge: bool = True) -> None:
    if acknowledge:
        _to_customer(ctx, "customer_ack", ticket)
    for agent in _queue_team_members(ctx, ticket):
        _to_agent(ctx, agent, "agent_new_ticket", ticket)


def ticket_assigned(ctx: Context, ticket: Ticket) -> None:
    if ticket.assignee is None:
        return
    agent = ctx.store.agents.get(ticket.assignee)
    if agent is not None:
        _to_agent(ctx, agent, "agent_assigned", ticket)


def agent_replied(ctx: Context, ticket: Ticket, comment: Comment) -> None:
    _to_customer(ctx, "customer_reply", ticket, comment=comment)


def customer_replied(ctx: Context, ticket: Ticket, comment: Comment) -> None:
    if ticket.assignee:
        agent = ctx.store.agents.get(ticket.assignee)
        if agent is not None:
            _to_agent(ctx, agent, "agent_customer_replied", ticket, comment=comment)
        return
    for agent in _queue_team_members(ctx, ticket):
        _to_agent(ctx, agent, "agent_customer_replied", ticket, comment=comment)


def sla_breached(ctx: Context, ticket: Ticket, target: str, due: str) -> None:
    breach = {"target": target.replace("_", " "), "due": due}
    recipients: list[Agent] = []
    if ticket.assignee and ticket.assignee in ctx.store.agents:
        recipients.append(ctx.store.agents[ticket.assignee])
    else:
        recipients.extend(_queue_team_members(ctx, ticket))
    for agent in recipients:
        _to_agent(ctx, agent, "agent_sla_breach", ticket, breach=breach)


def survey_sent(ctx: Context, ticket: Ticket, survey: Survey) -> None:
    _to_customer(ctx, "survey_request", ticket, survey=survey.to_dict())
