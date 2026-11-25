"""How the CLI prints records."""

from __future__ import annotations

from ..models import Agent, Customer, Macro, SavedSearch, Ticket
from ..redact import value
from ..store import Store
from ..textutil import table, truncate, wrap


def ticket_detail(
    store: Store, ticket: Ticket, *, internal: bool = True, hide: bool = False
) -> str:
    customer = store.customers.get(ticket.customer_id)
    lines = [
        f"{ticket.id}  {ticket.subject}",
        f"  status:    {ticket.status}" + (f" (merged into {ticket.merged_into})" if ticket.merged_into else ""),
        f"  priority:  {ticket.priority}",
        f"  queue:     {ticket.queue}",
        f"  assignee:  {ticket.assignee or '-'}",
        f"  tags:      {', '.join(ticket.tags) or '-'}",
    ]
    if customer is not None:
        lines.append(f"  requester: {customer.name} ({customer.id})")
        if customer.email:
            lines.append(f"  email:     {value(customer.email, hide)}")
        if customer.phone:
            lines.append(f"  phone:     {value(customer.phone, hide)}")
    else:
        lines.append(f"  requester: {ticket.customer_id}")
    lines.append(f"  created:   {ticket.created_at}")
    if ticket.due_first_response and not ticket.first_response_at:
        lines.append(f"  reply by:  {ticket.due_first_response}")
    if ticket.breaches:
        lines.append(f"  breached:  {', '.join(ticket.breaches)}")
    for comment in ticket.comments:
        if not comment.public and not internal:
            continue
        kind = "note" if not comment.public else comment.author_kind
        who = comment.author
        if comment.author_kind == "customer":
            who = customer.name if customer else comment.author
            if comment.from_address:
                who = f"{who} <{value(comment.from_address, hide)}>"
        lines.append("")
        lines.append(f"  #{comment.id} {comment.created_at} {kind} {who} via {comment.via}")
        lines.append(wrap(comment.body, 76, indent="    "))
    return "\n".join(lines) + "\n"


def ticket_rows(rows: list[dict]) -> str:
    if not rows:
        return "(no tickets)\n"
    body = [
        [
            r["id"],
            r["status"],
            r["priority"],
            r["queue"],
            r["assignee"] or "-",
            truncate(r["requester"], 20),
            r.get("requester_email") or "-",
            truncate(r["subject"], 40),
        ]
        for r in rows
    ]
    return table(["id", "status", "priority", "queue", "assignee", "requester", "email", "subject"], body) + "\n"


def customer_detail(customer: Customer, ticket_ids: list[str], *, hide: bool = False) -> str:
    lines = [
        f"{customer.id}  {customer.name}",
        f"  organization: {customer.organization or '-'}",
        f"  email:        {value(customer.email, hide) or '-'}",
        f"  phone:        {value(customer.phone, hide) or '-'}",
        f"  address:      {value(customer.address, hide) or '-'}",
        f"  tags:         {', '.join(customer.tags) or '-'}",
        f"  since:        {customer.created_at}",
        f"  tickets:      {', '.join(ticket_ids) or '-'}",
    ]
    return "\n".join(lines) + "\n"


def customer_rows(customers: list[Customer], *, hide: bool = False) -> str:
    if not customers:
        return "(no customers)\n"
    rows = [
        [
            c.id,
            truncate(c.name, 24),
            truncate(c.organization, 20) or "-",
            value(c.email, hide) or "-",
            value(c.phone, hide) or "-",
        ]
        for c in customers
    ]
    return table(["id", "name", "organization", "email", "phone"], rows) + "\n"


def agent_rows(agents: list[Agent]) -> str:
    rows = [
        [a.id, a.name, a.email, a.role, "yes" if a.active else "no", ", ".join(a.teams) or "-"]
        for a in agents
    ]
    return table(["id", "name", "email", "role", "active", "teams"], rows) + "\n"


def macro_rows(macros: list[Macro]) -> str:
    rows = []
    for m in macros:
        steps = "; ".join(
            a["type"] + (f"={truncate(a['value'], 20)}" if a.get("value") else "") for a in m.actions
        )
        rows.append([m.id, m.name, steps])
    return table(["id", "name", "actions"], rows) + "\n"


def search_rows(searches: list[SavedSearch]) -> str:
    rows = [[s.id, s.name, s.owner, "yes" if s.shared else "no", s.query] for s in searches]
    return table(["id", "name", "owner", "shared", "query"], rows) + "\n"
