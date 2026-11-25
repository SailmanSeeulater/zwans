"""Saved searches: named queries an agent keeps, optionally shared with everyone."""

from __future__ import annotations

from typing import Any

from .. import query
from ..context import Context
from ..errors import Conflict, NotFound, ValidationError
from ..models import SavedSearch, Ticket
from ..store import Store


def save_search(
    ctx: Context, name: str, text: str, *, shared: bool = False, sort: str = "updated"
) -> SavedSearch:
    name = name.strip()
    if not name:
        raise ValidationError("a saved search needs a name")
    if sort not in query.SORTS:
        raise ValidationError(f"cannot sort by {sort!r}")
    query.tokenize(text)
    with ctx.store.transaction():
        search = SavedSearch(
            id=ctx.store.next_id("search", "Q"),
            name=name,
            query=text,
            owner=ctx.actor_name,
            shared=shared,
            sort=sort,
        )
        ctx.store.searches[search.id] = search
        ctx.record("search.saved", search.id, name=name, query=text, shared=shared)
    return search


def _visible(ctx: Context, search: SavedSearch) -> bool:
    return ctx.is_system or search.shared or search.owner == ctx.actor_name


def list_searches(ctx: Context) -> list[SavedSearch]:
    found = [s for s in ctx.store.searches.values() if _visible(ctx, s)]
    return sorted(found, key=lambda s: int(s.id.split("-")[1]))


def get_search(ctx: Context, search_id: str) -> SavedSearch:
    search = ctx.store.saved_search(search_id)
    if not _visible(ctx, search):
        raise NotFound("saved search", search_id)
    return search


def delete_search(ctx: Context, search_id: str) -> None:
    with ctx.store.transaction():
        search = get_search(ctx, search_id)
        if not ctx.is_system and search.owner != ctx.actor_name:
            raise Conflict("only its owner can delete a saved search")
        del ctx.store.searches[search.id]
        ctx.record("search.deleted", search.id, name=search.name)


def _row(store: Store, ticket: Ticket) -> dict[str, Any]:
    customer = store.customers.get(ticket.customer_id)
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "queue": ticket.queue,
        "assignee": ticket.assignee,
        "tags": list(ticket.tags),
        "requester": customer.name if customer else ticket.customer_id,
        "requester_email": customer.email if customer else "",
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }


def run_saved(ctx: Context, search_id: str, *, limit: int | None = None) -> dict[str, Any]:
    search = get_search(ctx, search_id)
    predicate = query.compile_query(search.query, me=ctx.actor)
    found = query.select(ctx.store, predicate, search.sort)
    if limit is not None:
        found = found[:limit]
    return {
        "search": {"id": search.id, "name": search.name, "query": search.query},
        "count": len(found),
        "results": [_row(ctx.store, ticket) for ticket in found],
    }
