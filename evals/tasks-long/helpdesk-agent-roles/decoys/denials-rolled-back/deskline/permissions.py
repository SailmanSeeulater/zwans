"""Roles and what they allow.

The system (a context without an agent) may do everything. For agents, ``GRANTS`` maps
each permission to the roles that have it; ``ticket.edit`` is special for the ``agent``
role, which has it only on tickets that are unassigned or assigned to them.
"""

from __future__ import annotations

from . import audit
from .context import Context
from .errors import PermissionDenied, ValidationError
from .models import ROLES, Ticket

EVERYONE = frozenset(ROLES)
WORKERS = frozenset({"agent", "lead", "admin"})
LEADS = frozenset({"lead", "admin"})
ADMINS = frozenset({"admin"})

GRANTS: dict[str, frozenset[str]] = {
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

# Search terms that look at contact details.
CONTACT_TERMS = ("email", "phone")


def check_role(role: str) -> str:
    if role not in ROLES:
        raise ValidationError(f"unknown role {role!r} (one of {', '.join(ROLES)})")
    return role


def role_allows(role: str | None, permission: str, *, owner_ok: bool = True) -> bool:
    if role is None:
        return True
    if permission == "ticket.edit" and role == "agent":
        return owner_ok
    return role in GRANTS[permission]


def allowed(ctx: Context, permission: str, *, ticket: Ticket | None = None) -> bool:
    if permission not in GRANTS:
        raise KeyError(permission)
    if ctx.is_system:
        return True
    owner_ok = ticket is None or ticket.assignee in (None, ctx.actor)
    return role_allows(ctx.role, permission, owner_ok=owner_ok)


def sees_contacts(ctx: Context) -> bool:
    return allowed(ctx, "contact.view")


def deny(ctx: Context, permission: str, target: str = "desk") -> PermissionDenied:
    """Record a refusal in the audit log (it survives the rollback) and build the error."""
    actor, at, role = ctx.actor, ctx.now(), ctx.role
    target = target or "desk"

    def keep(store) -> None:
        audit.record(
            store, at, actor, "permission.denied", target, {"permission": permission, "role": role}
        )

    if ctx.store.in_transaction:
        keep(ctx.store)
    else:
        ctx.store.afterwards(keep)
    return PermissionDenied(ctx.actor_name, permission, target)


def require(
    ctx: Context, permission: str, *, ticket: Ticket | None = None, target: str | None = None
) -> None:
    if allowed(ctx, permission, ticket=ticket):
        return
    raise deny(ctx, permission, target or (ticket.id if ticket is not None else "desk"))


def require_assign(ctx: Context, ticket: Ticket, agent_id: str | None) -> None:
    """Assigning to yourself is taking (ticket.edit); anything else is ticket.assign."""
    if agent_id is not None and agent_id == ctx.actor:
        require(ctx, "ticket.edit", ticket=ticket)
    else:
        require(ctx, "ticket.assign", ticket=ticket)


def require_query(ctx: Context, text: str) -> None:
    """Searching on contact details needs contact.view."""
    from . import query

    if query.terms_on(text, CONTACT_TERMS):
        require(ctx, "contact.view")
