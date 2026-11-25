"""Who has how much on their plate."""

from __future__ import annotations

from typing import Any

from ..context import Context
from ..textutil import table


def build(ctx: Context) -> dict[str, Any]:
    agents: dict[str, dict[str, int]] = {}
    for agent in sorted(ctx.store.agents.values(), key=lambda a: a.id):
        if agent.active:
            agents[agent.id] = {"new": 0, "open": 0, "pending": 0, "solved": 0}
    queues: dict[str, dict[str, int]] = {}
    for ticket in ctx.store.tickets.values():
        if ticket.merged_into:
            continue
        q = queues.setdefault(ticket.queue, {"active": 0, "unassigned": 0})
        if ticket.is_active:
            q["active"] += 1
            if ticket.assignee is None:
                q["unassigned"] += 1
        if ticket.assignee in agents and ticket.status in agents[ticket.assignee]:
            agents[ticket.assignee][ticket.status] += 1
    return {"agents": agents, "queues": dict(sorted(queues.items()))}


def render(report: dict[str, Any]) -> str:
    rows = [
        [agent, str(c["new"]), str(c["open"]), str(c["pending"]), str(c["solved"])]
        for agent, c in report["agents"].items()
    ]
    out = [table(["agent", "new", "open", "pending", "solved"], rows), ""]
    rows = [[q, str(c["active"]), str(c["unassigned"])] for q, c in report["queues"].items()]
    out.append(table(["queue", "active", "unassigned"], rows))
    return "\n".join(out) + "\n"
