"""Satisfaction: survey ratings by agent and queue, and the unhappy customers to follow up."""

from __future__ import annotations

from typing import Any

from ..context import Context
from ..services import surveys
from ..textutil import table

LOW_RATING = 2


def _average(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def build(ctx: Context, *, since: str | None = None) -> dict[str, Any]:
    ratings: list[int] = []
    by_agent: dict[str, list[int]] = {}
    by_queue: dict[str, list[int]] = {}
    follow_up = []
    for survey in surveys.answered(ctx, since):
        ticket = ctx.store.tickets.get(survey.ticket_id)
        if ticket is None or survey.rating is None:
            continue
        ratings.append(survey.rating)
        by_agent.setdefault(ticket.assignee or "-", []).append(survey.rating)
        by_queue.setdefault(ticket.queue, []).append(survey.rating)
        if survey.rating <= LOW_RATING:
            customer = ctx.store.customers.get(ticket.customer_id)
            follow_up.append(
                {
                    "ticket": ticket.id,
                    "rating": survey.rating,
                    "remark": survey.remark,
                    "agent": ticket.assignee,
                    "customer": customer.name if customer else ticket.customer_id,
                    "email": customer.email if customer else "",
                    "phone": customer.phone if customer else "",
                }
            )
    sent = len(ctx.store.surveys)
    return {
        "sent": sent,
        "responses": len(ratings),
        "response_rate": round(len(ratings) / sent, 3) if sent else 0.0,
        "average": _average(ratings),
        "by_agent": {k: _average(v) for k, v in sorted(by_agent.items())},
        "by_queue": {k: _average(v) for k, v in sorted(by_queue.items())},
        "follow_up": follow_up,
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        f"Surveys sent: {report['sent']}, answered: {report['responses']}, "
        f"average: {report['average'] if report['average'] is not None else '-'}",
        "",
    ]
    rows = [[agent, str(avg)] for agent, avg in report["by_agent"].items()]
    lines.append(table(["agent", "average"], rows))
    if report["follow_up"]:
        lines += ["", "Follow up:"]
        rows = [
            [f["ticket"], str(f["rating"]), f["customer"], f["email"] or "-", f["phone"] or "-"]
            for f in report["follow_up"]
        ]
        lines.append(table(["ticket", "rating", "customer", "email", "phone"], rows))
    return "\n".join(lines) + "\n"
