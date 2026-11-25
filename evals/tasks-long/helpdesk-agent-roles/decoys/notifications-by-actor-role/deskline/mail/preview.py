"""Previewing a template against a real ticket, as the agent asking would see it."""

from __future__ import annotations

from typing import Any

from ..context import Context
from ..permissions import require, sees_contacts
from ..redact import value
from . import templates


def preview(ctx: Context, name: str, ticket_id: str) -> dict[str, Any]:
    template = templates.get(name)
    ticket = ctx.store.ticket(ticket_id)
    require(ctx, "ticket.view", ticket=ticket)
    hide = not sees_contacts(ctx)
    context = templates.ticket_context(ctx.store, ticket, hide=hide)
    last = ticket.comments[-1] if ticket.comments else None
    if last is not None:
        context["comment"] = last.to_dict()
        context["comment"]["from_address"] = value(last.from_address, hide)
    agent = ctx.agent
    context["recipient"] = {"id": agent.id, "name": agent.name} if agent else {"name": "Agent"}
    context.setdefault("breach", {"target": "resolution", "due": ticket.due_resolution or ""})
    context.setdefault("survey", {"token": "PREVIEW"})
    subject, body = templates.render(name, context)
    return {"template": name, "audience": template.audience, "subject": subject, "body": body}


def list_templates() -> list[dict[str, str]]:
    return [
        {"name": t.name, "audience": t.audience, "subject": t.subject}
        for t in sorted(templates.BUILTIN.values(), key=lambda t: t.name)
    ]
