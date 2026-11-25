"""Service-level targets: when a ticket must get its first reply and be solved.

Targets are calendar minutes from the ticket's creation, by priority. The breach job
(``check_breaches``) marks tickets whose targets have passed and tells their agents.
"""

from __future__ import annotations

from ..clock import add_minutes, minutes_between
from ..context import Context
from ..errors import ValidationError
from ..models import PRIORITIES, SlaPolicy, Ticket
from ..store import Store

DEFAULT_POLICIES = {
    "urgent": SlaPolicy("urgent", 30, 240),
    "high": SlaPolicy("high", 60, 480),
    "normal": SlaPolicy("normal", 240, 1440),
    "low": SlaPolicy("low", 480, 2880),
}

TARGETS = ("first_response", "resolution")


def policy_for(store: Store, priority: str) -> SlaPolicy:
    return store.sla.get(priority) or DEFAULT_POLICIES[priority]


def policies(store: Store) -> list[SlaPolicy]:
    return [policy_for(store, p) for p in PRIORITIES]


def set_policy(ctx: Context, priority: str, first_response: int, resolution: int) -> SlaPolicy:
    if priority not in PRIORITIES:
        raise ValidationError(f"unknown priority {priority!r}")
    if first_response <= 0 or resolution <= 0:
        raise ValidationError("SLA targets must be positive numbers of minutes")
    if resolution < first_response:
        raise ValidationError("the resolution target cannot be shorter than the first reply")
    with ctx.store.transaction():
        old = policy_for(ctx.store, priority)
        policy = SlaPolicy(priority, first_response, resolution)
        ctx.store.sla[priority] = policy
        for ticket in ctx.store.tickets.values():
            if ticket.priority == priority and ticket.is_active:
                apply_targets(ctx.store, ticket)
        ctx.record(
            "sla.policy_changed",
            priority,
            first_response=[old.first_response_minutes, first_response],
            resolution=[old.resolution_minutes, resolution],
        )
    return policy


def apply_targets(store: Store, ticket: Ticket) -> None:
    policy = policy_for(store, ticket.priority)
    ticket.due_first_response = add_minutes(ticket.created_at, policy.first_response_minutes)
    ticket.due_resolution = add_minutes(ticket.created_at, policy.resolution_minutes)


def breach_state(ticket: Ticket, now: str) -> dict[str, bool]:
    """Which targets this ticket has missed, as of ``now``."""
    state = {}
    responded = ticket.first_response_at
    state["first_response"] = bool(
        ticket.due_first_response
        and ((responded or now) > ticket.due_first_response)
    )
    finished = ticket.solved_at or ticket.closed_at
    state["resolution"] = bool(
        ticket.due_resolution and ((finished or now) > ticket.due_resolution)
    )
    return state


def check_breaches(ctx: Context) -> list[tuple[str, str]]:
    """Mark newly breached targets, tell the agents, and return (ticket, target) pairs."""
    from .. import notify

    found = []
    now = ctx.now()
    with ctx.store.transaction():
        for ticket in sorted(ctx.store.tickets.values(), key=lambda t: t.created_at):
            if ticket.merged_into:
                continue
            for target, missed in breach_state(ticket, now).items():
                if not missed or target in ticket.breaches:
                    continue
                ticket.breaches.append(target)
                due = ticket.due_first_response if target == "first_response" else ticket.due_resolution
                found.append((ticket.id, target))
                ctx.record("sla.breached", ticket.id, target=target, due=due)
                if ticket.is_active:
                    notify.sla_breached(ctx, ticket, target, due or "")
    return found


def overdue_minutes(ticket: Ticket, target: str, now: str) -> int:
    due = ticket.due_first_response if target == "first_response" else ticket.due_resolution
    if not due:
        return 0
    if target == "first_response":
        end = ticket.first_response_at or now
    else:
        end = ticket.solved_at or ticket.closed_at or now
    return max(minutes_between(due, end), 0)
