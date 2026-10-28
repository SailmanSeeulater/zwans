"""Roles, what they allow, and who holds them.

Roles are defined in the configuration under `[roles.<name>]`:

- `permissions`: the permissions the role grants itself;
- `inherits`: roles whose permissions (and so on, recursively) this role also grants;
- `limit_eur`: the largest amount, in euros, the role may approve. A role without its own
  `limit_eur` takes the highest limit among the roles it inherits from.

Roles are given to groups by `[[bindings]]` entries (`group`, `role`); every member of the
group holds the role *directly*. Roles can also be held through a delegation or granted
by a plugin; see ledgerdesk.policy.engine.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ledgerdesk.directory import Directory


class RoleError(Exception):
    pass


@dataclass(frozen=True)
class Role:
    name: str
    permissions: frozenset[str]
    limit_eur: Decimal | None


class RoleBook:
    def __init__(self, definitions: dict[str, dict[str, Any]]):
        self._definitions = definitions
        self._roles: dict[str, Role] = {}
        for name in definitions:
            self._resolve(name, ())

    def _resolve(self, name: str, seen: tuple[str, ...]) -> Role:
        if name in self._roles:
            return self._roles[name]
        if name in seen:
            raise RoleError(f"role inheritance cycle: {' -> '.join((*seen, name))}")
        if name not in self._definitions:
            raise RoleError(f"unknown role {name!r}")
        spec = self._definitions[name]
        permissions = set(spec.get("permissions", []))
        inherited_limits: list[Decimal] = []
        for parent_name in spec.get("inherits", []):
            parent = self._resolve(parent_name, (*seen, name))
            permissions |= parent.permissions
            if parent.limit_eur is not None:
                inherited_limits.append(parent.limit_eur)
        if "limit_eur" in spec:
            limit: Decimal | None = Decimal(str(spec["limit_eur"]))
        else:
            limit = max(inherited_limits) if inherited_limits else None
        role = Role(name, frozenset(permissions), limit)
        self._roles[name] = role
        return role

    def get(self, name: str) -> Role:
        try:
            return self._roles[name]
        except KeyError:
            raise RoleError(f"unknown role {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._roles)


@dataclass(frozen=True)
class Binding:
    group: str
    role: str


def load_bindings(config: dict[str, Any], roles: RoleBook, directory: Directory) -> list[Binding]:
    bindings = []
    for entry in config.get("bindings", []):
        binding = Binding(entry["group"], entry["role"])
        roles.get(binding.role)  # fail early on typos
        directory.members(binding.group)
        bindings.append(binding)
    return bindings


def direct_roles(username: str, bindings: list[Binding], directory: Directory) -> list[str]:
    """The roles `username` holds through group bindings, in binding order, without repeats."""
    held: list[str] = []
    for binding in bindings:
        if username in directory.members(binding.group) and binding.role not in held:
            held.append(binding.role)
    return held
