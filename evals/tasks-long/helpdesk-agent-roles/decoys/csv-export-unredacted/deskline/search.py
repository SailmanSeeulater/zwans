"""Ticket search: runs a query and returns result rows."""

from __future__ import annotations

from typing import Any

from . import query, views
from .context import Context
from .permissions import require, require_query, sees_contacts


def run(
    ctx: Context, text: str, *, sort: str = "updated", limit: int | None = None
) -> list[dict[str, Any]]:
    require(ctx, "ticket.view")
    require_query(ctx, text)
    hide = not sees_contacts(ctx)
    predicate = query.compile_query(text, me=ctx.actor)
    found = query.select(ctx.store, predicate, sort)
    if limit is not None:
        found = found[:limit]
    return [views.ticket_row(ctx.store, ticket, hide=hide) for ticket in found]


def count(ctx: Context, text: str) -> int:
    require(ctx, "ticket.view")
    require_query(ctx, text)
    predicate = query.compile_query(text, me=ctx.actor)
    return sum(1 for t in ctx.store.tickets.values() if predicate(ctx.store, t))
