"""Plain-dict views of records, as the JSON API and ticket search return them."""

from __future__ import annotations

from typing import Any

from .models import Agent, Comment, Customer, Macro, SavedSearch, Team, Ticket
from .redact import value
from .store import Store


def customer_view(
    customer: Customer, *, ticket_ids: list[str] | None = None, hide: bool = False
) -> dict[str, Any]:
    data = {
        "id": customer.id,
        "name": customer.name,
        "email": value(customer.email, hide),
        "phone": value(customer.phone, hide),
        "address": value(customer.address, hide),
        "organization": customer.organization,
        "tags": list(customer.tags),
        "created_at": customer.created_at,
    }
    if ticket_ids is not None:
        data["tickets"] = list(ticket_ids)
    return data


def requester_view(store: Store, customer_id: str, *, hide: bool = False) -> dict[str, Any]:
    customer = store.customers.get(customer_id)
    if customer is None:
        return {"id": customer_id, "name": "(unknown)", "email": "", "phone": ""}
    return {
        "id": customer.id,
        "name": customer.name,
        "email": value(customer.email, hide),
        "phone": value(customer.phone, hide),
        "organization": customer.organization,
    }


def comment_view(comment: Comment, *, hide: bool = False) -> dict[str, Any]:
    return {
        "id": comment.id,
        "author_kind": comment.author_kind,
        "author": comment.author,
        "body": comment.body,
        "public": comment.public,
        "created_at": comment.created_at,
        "via": comment.via,
        "from_address": value(comment.from_address, hide),
    }


def ticket_view(
    store: Store, ticket: Ticket, *, internal: bool = True, hide: bool = False
) -> dict[str, Any]:
    comments = ticket.comments if internal else ticket.public_comments()
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "queue": ticket.queue,
        "assignee": ticket.assignee,
        "tags": list(ticket.tags),
        "requester": requester_view(store, ticket.customer_id, hide=hide),
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "first_response_at": ticket.first_response_at,
        "solved_at": ticket.solved_at,
        "closed_at": ticket.closed_at,
        "merged_into": ticket.merged_into,
        "due": {"first_response": ticket.due_first_response, "resolution": ticket.due_resolution},
        "breaches": list(ticket.breaches),
        "comments": [comment_view(c, hide=hide) for c in comments],
    }


def ticket_row(store: Store, ticket: Ticket, *, hide: bool = False) -> dict[str, Any]:
    """The short form used in lists and search results."""
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
        "requester_email": value(customer.email, hide) if customer else "",
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }


def agent_view(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "active": agent.active,
        "teams": list(agent.teams),
        "role": agent.role,
    }


def team_view(team: Team) -> dict[str, Any]:
    return {"id": team.id, "name": team.name, "members": list(team.members)}


def macro_view(macro: Macro) -> dict[str, Any]:
    return {
        "id": macro.id,
        "name": macro.name,
        "actions": [dict(a) for a in macro.actions],
        "created_by": macro.created_by,
    }


def search_view(search: SavedSearch) -> dict[str, Any]:
    return {
        "id": search.id,
        "name": search.name,
        "query": search.query,
        "owner": search.owner,
        "shared": search.shared,
        "sort": search.sort,
    }
