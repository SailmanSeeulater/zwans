"""The people directory: users and the groups they belong to.

`data/directory.json` holds two lists:

- `users`: one object per user with `username`, `name`, `department`, `type` (`employee`,
  `contractor` or `service`), `utc_offset` (like `+01:00`) and `active`.
- `groups`: one object per group with `name` and `members`. A member is a username, or
  `@other-group` to include every member of another group. Groups can nest to any depth.

Deactivated users (`"active": false`) stay in the file for the audit trail but are never
members of any group and never act on anything.
"""

import json
from dataclasses import dataclass
from pathlib import Path

USER_TYPES = ("employee", "contractor", "service")


class DirectoryError(Exception):
    pass


@dataclass(frozen=True)
class User:
    username: str
    name: str
    department: str
    type: str
    utc_offset: str
    active: bool = True

    @property
    def is_contractor(self) -> bool:
        return self.type == "contractor"


class Directory:
    def __init__(self, users: list[User], groups: dict[str, list[str]]):
        self._users = {user.username: user for user in users}
        self._groups = groups
        self._expanded: dict[str, frozenset[str]] = {}
        for name, members in groups.items():
            for member in members:
                if member.startswith("@"):
                    if member[1:] not in groups:
                        raise DirectoryError(f"group {name} includes unknown group {member}")
                elif member not in self._users:
                    raise DirectoryError(f"group {name} includes unknown user {member}")

    # -- users ----------------------------------------------------------------------------

    def user(self, username: str) -> User:
        try:
            return self._users[username]
        except KeyError:
            raise DirectoryError(f"no such user {username!r}") from None

    def has_user(self, username: str) -> bool:
        return username in self._users

    def users(self, include_inactive: bool = False) -> list[User]:
        users = sorted(self._users.values(), key=lambda user: user.username)
        return users if include_inactive else [user for user in users if user.active]

    # -- groups ---------------------------------------------------------------------------

    def group_names(self) -> list[str]:
        return sorted(self._groups)

    def members(self, group: str) -> frozenset[str]:
        """Every active user in `group`, including members of nested groups."""
        if group not in self._groups:
            raise DirectoryError(f"no such group {group!r}")
        if group not in self._expanded:
            self._expanded[group] = frozenset(
                name for name in self._walk(group, ()) if self._users[name].active
            )
        return self._expanded[group]

    def _walk(self, group: str, seen: tuple[str, ...]) -> set[str]:
        if group in seen:
            chain = " -> ".join((*seen, group))
            raise DirectoryError(f"group cycle: {chain}")
        found: set[str] = set()
        for member in self._groups[group]:
            if member.startswith("@"):
                found |= self._walk(member[1:], (*seen, group))
            else:
                found.add(member)
        return found

    def groups_of(self, username: str) -> list[str]:
        """The groups `username` is a member of, directly or through nesting."""
        return [name for name in self.group_names() if username in self.members(name)]


def load_directory(path: Path) -> Directory:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    users = []
    for entry in raw["users"]:
        if entry.get("type", "employee") not in USER_TYPES:
            raise DirectoryError(f"{entry['username']}: unknown user type {entry['type']!r}")
        users.append(
            User(
                username=entry["username"],
                name=entry["name"],
                department=entry["department"],
                type=entry.get("type", "employee"),
                utc_offset=entry.get("utc_offset", "+00:00"),
                active=entry.get("active", True),
            )
        )
    groups = {group["name"]: list(group["members"]) for group in raw["groups"]}
    return Directory(users, groups)
