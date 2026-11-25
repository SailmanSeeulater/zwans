"""Changing many tickets at once.

``changes`` may hold ``status``, ``priority``, ``queue``, ``assignee`` (an agent id, or
``""`` to unassign), ``add_tags`` and ``remove_tags`` (lists). The changes are made to
every ticket in order; if any of them fails, no ticket is changed.
"""

from __future__ import annotations

from typing import Any

from ..context import Context
from ..errors import ValidationError
from ..models import Ticket
from ..permissions import require, require_assign
from . import tickets

KEYS = ("status", "priority", "queue", "assignee", "add_tags", "remove_tags")


def _validate(changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(KEYS)
    if unknown:
        raise ValidationError(f"cannot bulk-change {', '.join(sorted(unknown))}")
    clean = {k: v for k, v in changes.items() if v is not None}
    if not clean:
        raise ValidationError("nothing to change")
    for key in ("add_tags", "remove_tags"):
        if key in clean and isinstance(clean[key], str):
            clean[key] = [clean[key]]
    return clean


def check_changes(ctx: Context, ticket: Ticket, changes: dict[str, Any]) -> None:
    """Every change needs what it would need on its own."""
    if "assignee" in changes:
        require_assign(ctx, ticket, changes["assignee"] or None)
    if set(changes) - {"assignee"}:
        require(ctx, "ticket.edit", ticket=ticket)


def apply_changes(ctx: Context, ticket: Ticket, changes: dict[str, Any]) -> None:
    if "queue" in changes:
        tickets.change_queue(ctx, ticket, changes["queue"])
    if "priority" in changes:
        tickets.change_priority(ctx, ticket, changes["priority"])
    if "assignee" in changes:
        tickets.change_assignee(ctx, ticket, changes["assignee"] or None)
    for name in changes.get("add_tags", []):
        tickets.tag(ctx, ticket, name)
    for name in changes.get("remove_tags", []):
        tickets.untag(ctx, ticket, name)
    if "status" in changes:
        tickets.change_status(ctx, ticket, changes["status"])


def bulk_update(ctx: Context, ticket_ids: list[str], changes: dict[str, Any]) -> list[Ticket]:
    if not ticket_ids:
        raise ValidationError("no tickets given")
    clean = _validate(changes)
    ids = list(dict.fromkeys(ticket_ids))
    with ctx.store.transaction():
        changed = []
        for ticket_id in ids:
            ticket = ctx.store.ticket(ticket_id)
            if ticket_id == ids[0]:
                check_changes(ctx, ticket, clean)
            apply_changes(ctx, ticket, clean)
            changed.append(ticket)
        ctx.record("ticket.bulk_updated", ",".join(ids), tickets=ids, changes=clean)
    return changed
