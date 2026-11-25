"""CSV exports of tickets and customers, for spreadsheets and the finance people."""

from __future__ import annotations

import csv
import io
from typing import IO

from .. import query
from ..context import Context
from ..permissions import require, require_query, sees_contacts
from ..redact import value

TICKET_COLUMNS = [
    "id",
    "subject",
    "status",
    "priority",
    "queue",
    "assignee",
    "tags",
    "requester",
    "requester_email",
    "requester_phone",
    "organization",
    "created_at",
    "updated_at",
    "first_response_at",
    "solved_at",
    "breaches",
    "comments",
]

CUSTOMER_COLUMNS = [
    "id",
    "name",
    "organization",
    "email",
    "phone",
    "address",
    "tags",
    "created_at",
    "tickets",
]


def export_tickets(ctx: Context, out: IO[str], *, text: str = "") -> int:
    require(ctx, "export")
    require_query(ctx, text)
    hide = False
    predicate = query.compile_query(text, me=ctx.actor)
    found = query.select(ctx.store, predicate, "id")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(TICKET_COLUMNS)
    for ticket in found:
        customer = ctx.store.customers.get(ticket.customer_id)
        writer.writerow(
            [
                ticket.id,
                ticket.subject,
                ticket.status,
                ticket.priority,
                ticket.queue,
                ticket.assignee or "",
                " ".join(ticket.tags),
                customer.name if customer else "",
                value(customer.email, hide) if customer else "",
                value(customer.phone, hide) if customer else "",
                customer.organization if customer else "",
                ticket.created_at,
                ticket.updated_at,
                ticket.first_response_at or "",
                ticket.solved_at or "",
                " ".join(ticket.breaches),
                len(ticket.public_comments()),
            ]
        )
    return len(found)


def export_customers(ctx: Context, out: IO[str]) -> int:
    require(ctx, "export")
    hide = False
    counts: dict[str, int] = {}
    for ticket in ctx.store.tickets.values():
        counts[ticket.customer_id] = counts.get(ticket.customer_id, 0) + 1
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CUSTOMER_COLUMNS)
    customers = sorted(ctx.store.customers.values(), key=lambda c: int(c.id.split("-")[1]))
    for customer in customers:
        writer.writerow(
            [
                customer.id,
                customer.name,
                customer.organization,
                value(customer.email, hide),
                value(customer.phone, hide),
                value(customer.address, hide),
                " ".join(customer.tags),
                customer.created_at,
                counts.get(customer.id, 0),
            ]
        )
    return len(customers)


def tickets_csv(ctx: Context, text: str = "") -> str:
    buffer = io.StringIO()
    export_tickets(ctx, buffer, text=text)
    return buffer.getvalue()


def customers_csv(ctx: Context) -> str:
    buffer = io.StringIO()
    export_customers(ctx, buffer)
    return buffer.getvalue()
