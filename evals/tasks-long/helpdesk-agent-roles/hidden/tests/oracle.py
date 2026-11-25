"""An independent statement of the README's permission table, for the scenario tests."""

from __future__ import annotations

EVERYONE = {"viewer", "agent", "lead", "admin"}
WORKERS = {"agent", "lead", "admin"}
LEADS = {"lead", "admin"}
ADMINS = {"admin"}

TABLE = {
    "ticket.view": EVERYONE,
    "customer.view": EVERYONE,
    "ticket.create": WORKERS,
    "ticket.note": WORKERS,
    "ticket.edit": WORKERS,
    "ticket.assign": LEADS,
    "ticket.delete": ADMINS,
    "customer.edit": WORKERS,
    "customer.delete": ADMINS,
    "contact.view": LEADS,
    "macro.run": WORKERS,
    "macro.manage": LEADS,
    "search.save": WORKERS,
    "search.share": LEADS,
    "export": WORKERS,
    "audit.view": WORKERS,
    "sla.manage": ADMINS,
    "admin": ADMINS,
}


def has(role: str | None, actor: str | None, permission: str, assignee: str | None = None) -> bool:
    """Does ``actor`` (with ``role``; None for the system) have ``permission``?

    ``assignee`` is the ticket's current assignee, for ticket.edit.
    """
    if actor is None:
        return True
    if role not in TABLE[permission]:
        return False
    if permission == "ticket.edit" and role == "agent":
        return assignee is None or assignee == actor
    return True


def assign_permission(actor: str | None, new_assignee: str | None) -> str:
    return "ticket.edit" if new_assignee is not None and new_assignee == actor else "ticket.assign"


def missing(role, actor, needs: list[tuple[str, str | None]]) -> list[str]:
    """The permissions in ``needs`` ((permission, ticket assignee) pairs) that are missing."""
    return [perm for perm, assignee in needs if not has(role, actor, perm, assignee)]
