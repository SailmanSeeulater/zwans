"""The SLA report: how each priority is doing against its targets, and which tickets
have missed them (with the requester's details, so a lead can call them back)."""

from __future__ import annotations

from typing import Any

from ..context import Context
from ..models import PRIORITIES
from ..permissions import require, sees_contacts
from ..redact import value
from ..services import sla
from ..textutil import table


def build(ctx: Context, *, since: str | None = None, queue: str | None = None) -> dict[str, Any]:
    require(ctx, "ticket.view")
    hide = False
    now = ctx.now()
    by_priority = {p: {"tickets": 0, "breached": 0, "rate": 0.0} for p in PRIORITIES}
    breached = []
    for ticket in sorted(ctx.store.tickets.values(), key=lambda t: int(t.id.split("-")[1])):
        if ticket.merged_into:
            continue
        if since is not None and ticket.created_at < since:
            continue
        if queue is not None and ticket.queue != queue:
            continue
        row = by_priority[ticket.priority]
        row["tickets"] += 1
        missed = [target for target, hit in sla.breach_state(ticket, now).items() if hit]
        if not missed:
            continue
        row["breached"] += 1
        customer = ctx.store.customers.get(ticket.customer_id)
        for target in missed:
            breached.append(
                {
                    "ticket": ticket.id,
                    "subject": ticket.subject,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "assignee": ticket.assignee,
                    "target": target,
                    "due": ticket.due_first_response
                    if target == "first_response"
                    else ticket.due_resolution,
                    "overdue_minutes": sla.overdue_minutes(ticket, target, now),
                    "requester": customer.name if customer else ticket.customer_id,
                    "email": value(customer.email, hide) if customer else "",
                    "phone": value(customer.phone, hide) if customer else "",
                }
            )
    for row in by_priority.values():
        row["rate"] = round(row["breached"] / row["tickets"], 3) if row["tickets"] else 0.0
    return {
        "generated_at": now,
        "policies": [p.to_dict() for p in sla.policies(ctx.store)],
        "by_priority": by_priority,
        "breached": breached,
    }


def render(report: dict[str, Any]) -> str:
    lines = [f"SLA report, {report['generated_at']}", ""]
    rows = [
        [p, str(r["tickets"]), str(r["breached"]), f"{r['rate'] * 100:.1f}%"]
        for p, r in report["by_priority"].items()
    ]
    lines.append(table(["priority", "tickets", "breached", "rate"], rows))
    if report["breached"]:
        lines += ["", "Missed targets:"]
        rows = [
            [
                b["ticket"],
                b["priority"],
                b["target"],
                str(b["overdue_minutes"]),
                b["assignee"] or "-",
                b["requester"],
                b["email"] or "-",
                b["phone"] or "-",
            ]
            for b in report["breached"]
        ]
        lines.append(
            table(
                ["ticket", "priority", "target", "overdue", "assignee", "requester", "email", "phone"],
                rows,
            )
        )
    return "\n".join(lines) + "\n"
