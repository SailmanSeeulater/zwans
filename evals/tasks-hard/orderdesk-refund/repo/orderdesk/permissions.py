"""Who may do what.

Every command and every view names one permission. Roles are sets of permissions; an actor
has exactly one role. Unknown roles have no permissions at all.
"""

from dataclasses import dataclass

from .errors import PermissionDenied


@dataclass(frozen=True)
class Actor:
    name: str
    role: str


_CLERK = frozenset(
    {
        "orders.view",
        "orders.place",
        "orders.pay",
        "orders.ship",
        "orders.note",
    }
)

ROLES: dict[str, frozenset[str]] = {
    # Clerks run the day-to-day flow of orders.
    "clerk": _CLERK,
    # Managers can do everything clerks can, plus anything that gives money back or
    # looks at the books.
    "manager": _CLERK | {"orders.cancel", "reports.view", "audit.view"},
    # Auditors only look.
    "auditor": frozenset({"orders.view", "reports.view", "audit.view"}),
}


def can(actor: Actor, permission: str) -> bool:
    return permission in ROLES.get(actor.role, frozenset())


def require(actor: Actor, permission: str) -> None:
    if not can(actor, permission):
        raise PermissionDenied(f"{actor.name} ({actor.role}) is not allowed to {permission}")
