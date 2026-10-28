"""Delegations: one user lending some of their permissions to another for a while.

`data/delegations.json` is a list of objects:

    {"from": "jwagner", "to": "pschmidt", "permissions": ["invoice.approve"],
     "valid_from": "2025-11-10T00:00:00Z", "valid_until": "2025-11-14T16:00:00Z",
     "note": "..."}

A delegation is in force from `valid_from` (inclusive) to `valid_until` (exclusive). While
it is, the delegate holds each of the delegator's *direct* roles (the ones the delegator
gets from group bindings) that grants one of the listed permissions. Delegations do not
chain: roles someone holds only through a delegation cannot be delegated further.

With the `strict_delegation` feature on, a delegation only counts when the delegate works
in the same department as the delegator. Delegations from or to deactivated users never
count.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ledgerdesk.clock import parse_instant
from ledgerdesk.directory import Directory


@dataclass(frozen=True)
class Delegation:
    delegator: str
    delegate: str
    permissions: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    note: str = ""

    def in_force(self, at: datetime) -> bool:
        return self.valid_from <= at < self.valid_until


def load_delegations(path: Path) -> list[Delegation]:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return [
        Delegation(
            delegator=entry["from"],
            delegate=entry["to"],
            permissions=frozenset(entry["permissions"]),
            valid_from=parse_instant(entry["valid_from"]),
            valid_until=parse_instant(entry["valid_until"]),
            note=entry.get("note", ""),
        )
        for entry in raw
    ]


def delegations_to(
    username: str,
    delegations: list[Delegation],
    at: datetime,
    directory: Directory,
    strict: bool,
) -> list[Delegation]:
    """The delegations that give `username` something at the instant `at`."""
    found = []
    for delegation in delegations:
        if delegation.delegate != username or not delegation.in_force(at):
            continue
        delegator = directory.user(delegation.delegator)
        delegate = directory.user(delegation.delegate)
        if not (delegator.active and delegate.active):
            continue
        if strict and delegator.department != delegate.department:
            continue
        found.append(delegation)
    return found
